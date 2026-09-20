"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import yaml from "js-yaml";
import {
  adoptBenchmark,
  Benchmark,
  getQuota,
  importSuite,
  listBenchmarks,
  listModels,
  listSuites,
  Quota,
  RunOptions,
  SuiteDoc,
  listProviders,
  ProviderInfo,
} from "@/lib/api";

/* ── Benchmark ──────────────────────────────────────────────────
   "Benchmark" is the word the UI uses; the API says "suite". Three
   sources: the ones EvalBench ships, the user's own, or a YAML file.
   Selection is cheap; resolving to a real suite id (adopting a bundled
   one, importing an upload) only happens when a run actually starts. */

/* needsJudge: whether scoring supplied answers still needs a grader.
   Undefined means unknown (an uploaded YAML, or a suite stored before the
   flag existed) — the form then shows the grader rather than guess. */
/* calls: what one run costs the key, samples × (tests + judged tests),
   from the API. judgeCalls: the part that is grading, which is all a run
   on supplied answers spends. Unknown for an uploaded YAML — the server
   still decides — so the form says nothing rather than guess. */
export type BenchmarkChoice =
  | { kind: "bundled"; slug: string; label: string; tests: number; provider: string; model: string; needsJudge?: boolean; calls?: number; judgeCalls?: number }
  | { kind: "mine"; id: string; label: string; tests: number; provider: string; model: string; needsJudge?: boolean; calls?: number; judgeCalls?: number }
  | { kind: "upload"; suite: Record<string, unknown>; label: string; tests: number; provider: string; model: string; needsJudge?: boolean; calls?: number; judgeCalls?: number };

/* Why the server's key cannot pay for a run of `cost` calls, or null.
   The same rule the API applies, said before the click instead of as a
   400 after it. */
export function serverKeyBlocked(cost: number | undefined, quota: Quota | null): string | null {
  if (!quota || quota.cap == null) return null;
  if (cost == null) return quota.remaining === 0 ? "nothing left today on EvalBench's key" : null;
  if (quota.per_run != null && cost > quota.per_run)
    return `this run needs ${cost} calls · EvalBench's key covers up to ${quota.per_run} per run`;
  if (quota.remaining != null && cost > quota.remaining)
    return `this run needs ${cost} calls · ${quota.remaining} left today on EvalBench's key`;
  return null;
}

export async function resolveBenchmark(
  c: BenchmarkChoice
): Promise<{ id: string; name: string }> {
  if (c.kind === "mine") return { id: c.id, name: c.label };
  if (c.kind === "bundled") {
    const r = await adoptBenchmark(c.slug);
    return { id: r.id, name: r.name };
  }
  const r = await importSuite(c.suite);
  return { id: r.id, name: c.label };
}

export function useBenchmarks() {
  const [bundled, setBundled] = useState<Benchmark[]>([]);
  const [mine, setMine] = useState<SuiteDoc[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [b, m] = await Promise.all([listBenchmarks(), listSuites()]);
      setBundled(b);
      setMine(m);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  /* One entry per name, newest first. Adopted copies of bundled
     benchmarks are hidden here — they are already listed above under
     their proper title, and showing both is how a list gets to 69. */
  const mineDeduped = useMemo(() => {
    const seen = new Set<string>();
    const out: SuiteDoc[] = [];
    for (const s of mine) {
      if ((s as SuiteDoc & { bundled_slug?: string }).bundled_slug) continue;
      if (seen.has(s.name)) continue;
      seen.add(s.name);
      out.push(s);
    }
    return out;
  }, [mine]);

  return { bundled, mine: mineDeduped, error, reload: load };
}

export function BenchmarkPicker({
  value,
  onChange,
  bundled,
  mine,
  id = "benchmark",
}: {
  value: BenchmarkChoice | null;
  onChange: (c: BenchmarkChoice | null) => void;
  bundled: Benchmark[];
  mine: SuiteDoc[];
  id?: string;
}) {
  const [uploadErr, setUploadErr] = useState<string | null>(null);

  const key =
    value?.kind === "bundled"
      ? `b:${value.slug}`
      : value?.kind === "mine"
        ? `m:${value.id}`
        : value?.kind === "upload"
          ? "upload"
          : "";

  function pick(k: string) {
    if (k.startsWith("b:")) {
      const b = bundled.find((x) => x.slug === k.slice(2));
      if (b)
        onChange({
          kind: "bundled",
          slug: b.slug,
          label: b.title,
          tests: b.test_count,
          provider: b.provider,
          model: b.model,
          needsJudge: b.needs_judge,
          calls: b.calls,
          judgeCalls: b.calls != null ? b.calls - (b.samples ?? 1) * b.test_count : undefined,
        });
    } else if (k.startsWith("m:")) {
      const s = mine.find((x) => x._id === k.slice(2));
      if (s)
        onChange({
          kind: "mine",
          id: s._id,
          label: s.name,
          tests: s.test_count ?? s.tests?.length ?? 0,
          provider: s.provider ?? "ollama",
          model: s.model,
          needsJudge: s.needs_judge,
          calls: s.calls,
          judgeCalls:
            s.calls != null
              ? s.calls - (s.samples ?? 1) * (s.test_count ?? s.tests?.length ?? 0)
              : undefined,
        });
    } else {
      onChange(null);
    }
  }

  async function onFile(f: File | undefined) {
    setUploadErr(null);
    if (!f) return;
    try {
      const text = await f.text();
      const suite = yaml.load(text) as Record<string, unknown>;
      if (!suite || typeof suite !== "object" || !Array.isArray(suite.tests))
        throw new Error("That file doesn't look like a benchmark (no `tests:` list).");
      onChange({
        kind: "upload",
        suite,
        label: String(suite.name ?? f.name),
        tests: (suite.tests as unknown[]).length,
        provider: String(suite.provider ?? "ollama"),
        model: String(suite.model ?? ""),
      });
    } catch (e) {
      setUploadErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="space-y-2">
      <select
        id={id}
        className="field font-mono text-sm"
        value={key}
        onChange={(e) => pick(e.target.value)}
      >
        <option value="">— choose a benchmark —</option>
        <optgroup label="EvalBench benchmarks">
          {bundled.map((b) => (
            <option key={b.slug} value={`b:${b.slug}`}>
              {b.title} · {b.test_count} {b.test_count === 1 ? "test" : "tests"}
            </option>
          ))}
        </optgroup>
        {mine.length > 0 && (
          <optgroup label="Your benchmarks">
            {mine.map((s) => (
              <option key={s._id} value={`m:${s._id}`}>
                {s.name} · {s.test_count ?? s.tests?.length ?? 0}{" "}
                {(s.test_count ?? s.tests?.length ?? 0) === 1 ? "test" : "tests"}
              </option>
            ))}
          </optgroup>
        )}
        {value?.kind === "upload" && (
          <option value="upload">
            {value.label} · {value.tests} {value.tests === 1 ? "test" : "tests"} (uploaded)
          </option>
        )}
      </select>

      <label className="flex cursor-pointer items-baseline gap-2 text-xs text-muted">
        <span className="label-xs">or upload YAML</span>
        <input
          type="file"
          accept=".yaml,.yml"
          className="text-xs"
          onChange={(e) => onFile(e.target.files?.[0])}
        />
      </label>
      {uploadErr && <p className="text-xs text-error">{uploadErr}</p>}

      {value && (
        <div className="space-y-1">
          <p className="font-mono text-[11px] text-muted tnum">
            {value.tests} {value.tests === 1 ? "test" : "tests"}
            {value.kind === "bundled" &&
              ` · ${bundled.find((b) => b.slug === value.slug)?.categories.length ?? 0} categories`}
          </p>
          {/* What it measures — the sentence that makes the choice mean
              something before the numbers arrive. */}
          {(() => {
            const d =
              value.kind === "bundled"
                ? bundled.find((b) => b.slug === value.slug)?.description
                : value.kind === "mine"
                  ? mine.find((s) => s._id === value.id)?.description
                  : null;
            return d ? (
              <p className="max-w-xl text-xs leading-relaxed text-muted">{d}</p>
            ) : null;
          })()}
        </div>
      )}
    </div>
  );
}

/* ── Model ──────────────────────────────────────────────────────
   Provider + model name. The model list is fetched when the provider
   can enumerate its models; otherwise it is a free-text field, which
   is what the YAML format has always been. */

/* Fallback only — the real list comes from the API, which knows which
   providers this instance actually holds a key for. Hardcoding it is how
   the picker ended up offering five hosted providers when one had a key,
   and the failure surfaced as a dead run minutes later. */
const FALLBACK_PROVIDERS: ProviderInfo[] = [
  { id: "groq", label: "Groq", needs_key: true, server_key: false },
  { id: "ollama", label: "Ollama (local)", needs_key: false, server_key: false },
  {
    id: "custom",
    label: "My own endpoint",
    needs_key: false,
    server_key: false,
    needs_url: true,
  },
];

/* baseUrl / endpointKey belong to the choice, not to the shared key
   picker: in a comparison, A and B can be two different endpoints with
   two different keys. The key is optional — a personal model server
   behind a tunnel often has none. */
export type ModelChoice = {
  provider: string;
  model: string;
  baseUrl?: string;
  endpointKey?: string;
};

/** Whether the choice names a URL the server needs. */
export function needsUrl(provider: string, list?: ProviderInfo[] | null) {
  const all = list ?? providerCache ?? FALLBACK_PROVIDERS;
  return all.find((p) => p.id === provider)?.needs_url ?? provider === "custom";
}

/** Enough of a URL to send. The server does the real check and says why
    if it refuses; this only keeps the button honest. */
export function looksLikeUrl(s: string | undefined) {
  return !!s && /^https?:\/\/[^\s/]+/.test(s.trim());
}

/** A model choice the run button can accept. */
export function modelReady(m: ModelChoice) {
  return !!m.model && (!needsUrl(m.provider) || looksLikeUrl(m.baseUrl));
}

/** The request for this choice. `key` is the shared own-key field for
    hosted providers; a custom endpoint carries its own. */
export function toRunOptions(m: ModelChoice, key?: string): RunOptions {
  if (needsUrl(m.provider)) {
    return {
      model: m.model,
      provider: m.provider,
      base_url: m.baseUrl?.trim(),
      provider_key: m.endpointKey || undefined,
    };
  }
  return { model: m.model, provider: m.provider, provider_key: key };
}

/** Shared across pickers: fetched once, not per component. */
let providerCache: ProviderInfo[] | null = null;

/** The live list, or null until it arrives.

    Null matters: the fallback cannot know which keys this instance
    holds, so anything that *acts* on that — forcing own-key mode —
    must wait rather than decide from a guess. Rendering falls back
    happily; deciding does not. */
export function useProviders(): ProviderInfo[] | null {
  const [list, setList] = useState<ProviderInfo[] | null>(providerCache);
  useEffect(() => {
    if (providerCache) return;
    let alive = true;
    listProviders()
      .then((r) => {
        providerCache = r;
        if (alive) setList(r);
      })
      .catch(() => {
        /* leave it null — the fallback renders, nothing is forced */
      });
    return () => {
      alive = false;
    };
  }, []);
  return list;
}

/* Ready first: what runs on this instance's key with no setup, then what
   needs nothing (local, replayed), then what needs your key, then your
   own endpoint. The API sorts by id, which put "custom" above Groq. */
export function orderProviders(list: ProviderInfo[]): ProviderInfo[] {
  const rank = (p: ProviderInfo) =>
    p.needs_url ? 3 : p.server_key ? 0 : !p.needs_key ? 1 : 2;
  return [...list].sort((a, b) => rank(a) - rank(b) || a.label.localeCompare(b.label));
}

export function isHosted(provider: string, list?: ProviderInfo[] | null) {
  const all = list ?? providerCache ?? FALLBACK_PROVIDERS;
  return all.find((p) => p.id === provider)?.needs_key ?? true;
}

/** Whether this instance can run `provider` on its own key. */
export function hasServerKey(provider: string, list?: ProviderInfo[] | null) {
  const all = list ?? providerCache ?? FALLBACK_PROVIDERS;
  return all.find((p) => p.id === provider)?.server_key ?? false;
}

export function ModelPicker({
  value,
  onChange,
  idPrefix = "model",
}: {
  value: ModelChoice;
  onChange: (m: ModelChoice) => void;
  idPrefix?: string;
}) {
  const [models, setModels] = useState<string[]>([]);
  const providers = useProviders();

  useEffect(() => {
    let alive = true;
    setModels([]);
    listModels(value.provider)
      .then((r) => {
        if (!alive) return;
        const list = r.models ?? [];
        setModels(list);
        // An empty field with a greyed-out Run button tells the user
        // nothing. Prefill the first model the provider actually lists;
        // they can still overwrite it.
        if (!value.model && list.length > 0) {
          onChange({ provider: value.provider, model: list[0] });
        }
      })
      .catch(() => alive && setModels([]));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.provider]);

  const listId = `${idPrefix}-models`;
  const custom = needsUrl(value.provider, providers);

  return (
    <div className="space-y-2">
      <div className="grid gap-2 sm:grid-cols-[11rem_1fr]">
        <select
          id={`${idPrefix}-provider`}
          aria-label="Provider"
          className="field font-mono text-sm"
          value={value.provider}
          onChange={(e) =>
            onChange({
              provider: e.target.value,
              model: "",
              baseUrl: value.baseUrl,
              endpointKey: value.endpointKey,
            })
          }
        >
          {orderProviders(providers ?? FALLBACK_PROVIDERS).map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
              {p.needs_key && !p.server_key ? " · your key only" : ""}
            </option>
          ))}
        </select>
        <div>
          <input
            id={`${idPrefix}-name`}
            aria-label="Model"
            list={listId}
            className="field font-mono text-sm"
            placeholder="model name"
            value={value.model}
            onChange={(e) => onChange({ ...value, model: e.target.value })}
          />
          <datalist id={listId}>
            {models.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </div>
      </div>

      {/* Your own OpenAI-compatible endpoint. The server checks the URL
          — public https only, and it re-checks at connect time — and
          never sends its own keys to it. */}
      {custom && (
        <div className="space-y-2 border-l-2 border-line pl-3">
          <input
            id={`${idPrefix}-base-url`}
            aria-label="Endpoint base URL"
            type="url"
            className="field font-mono text-sm"
            placeholder="https://my-gateway.example.com/v1"
            spellCheck={false}
            value={value.baseUrl ?? ""}
            onChange={(e) => onChange({ ...value, baseUrl: e.target.value })}
          />
          <input
            id={`${idPrefix}-endpoint-key`}
            aria-label="Endpoint API key (optional)"
            type="password"
            className="field font-mono text-xs"
            placeholder="API key, if your endpoint needs one — encrypted, held only while the run executes"
            value={value.endpointKey ?? ""}
            onChange={(e) => onChange({ ...value, endpointKey: e.target.value })}
          />
          <p className="text-xs leading-relaxed text-muted">
            Anything that speaks the OpenAI chat API — vLLM, Ollama behind a
            tunnel, a gateway, a fine-tune you host. EvalBench appends{" "}
            <span className="font-mono text-text">/chat/completions</span>. Public
            https only; its own keys are never sent there. Type the model name
            your endpoint expects.
          </p>
        </div>
      )}
    </div>
  );
}

/* ── Key ────────────────────────────────────────────────────────
   Whose key pays for a hosted run. The cap is shown *before* the run,
   not discovered as a 429 after it. */

export type KeyMode = { own: boolean; key: string };

export function useQuota() {
  const [quota, setQuota] = useState<Quota | null>(null);
  const refresh = useCallback(() => {
    getQuota().then(setQuota).catch(() => setQuota(null));
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);
  return { quota, refresh };
}

export function KeyPicker({
  value,
  onChange,
  quota,
  provider,
  name = "keymode",
  cost,
}: {
  value: KeyMode;
  onChange: (k: KeyMode) => void;
  quota: Quota | null;
  provider: string;
  /** Radio group name — must differ per instance on a page, or two
   *  pickers become one group and uncheck each other. */
  name?: string;
  /** What the run this picker pays for will cost, in calls, if known. */
  cost?: number;
}) {
  const providers = useProviders();

  // Switching to a provider we hold no key for must also switch the mode,
  // or the form would submit "use EvalBench's key" while showing a field
  // for your own.
  const ownOnly =
    providers !== null &&
    isHosted(provider, providers) &&
    !hasServerKey(provider, providers);
  useEffect(() => {
    if (ownOnly && !value.own) onChange({ own: true, key: value.key });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ownOnly]);

  // The endpoint's key lives with the endpoint, in the model picker.
  if (needsUrl(provider, providers)) return null;

  if (!isHosted(provider, providers)) {
    return (
      <p className="text-xs text-muted">
        Local model — no key needed, nothing is spent.
      </p>
    );
  }

  // This instance holds no key for the provider, so there is nothing to
  // offer but your own. Showing the choice anyway is what let someone
  // pick GitHub Models, click run, and get a dead run back.
  if (ownOnly) {
    return (
      <div className="space-y-2 text-sm">
        <p className="text-xs text-muted">
          This EvalBench instance has no {provider} key, so this one runs
          on yours. It is encrypted, held only while the run executes,
          and deleted when it finishes. For real work, use the CLI — your
          key never leaves your machine.
        </p>
        <input
          type="password"
          className="field font-mono text-xs"
          placeholder={`${provider} API key`}
          value={value.key}
          onChange={(e) => onChange({ own: true, key: e.target.value })}
        />
      </div>
    );
  }

  /* When the shared cap is the tighter one, say so: "0 left" with 140
     of your own 150 unused reads as a bug otherwise. */
  const shared =
    quota?.instance != null &&
    quota.cap != null &&
    quota.instance.remaining < quota.cap - quota.used;
  const left =
    quota == null
      ? "…"
      : quota.cap == null
        ? "unlimited"
        : shared
          ? `${quota.remaining} calls left today · shared by everyone on this instance`
          : `${quota.remaining} of ${quota.cap} calls left today`;
  const blocked = serverKeyBlocked(cost, quota);
  const exhausted = blocked !== null;

  return (
    <div className="space-y-2 text-sm">
      <label className="flex items-baseline gap-2">
        <input
          type="radio"
          name={name}
          checked={!value.own}
          disabled={exhausted}
          onChange={() => onChange({ own: false, key: "" })}
        />
        <span>
          Use EvalBench&rsquo;s key{" "}
          <span className={`font-mono text-[11px] tnum ${exhausted ? "text-error" : "text-muted"}`}>
            · {blocked ?? left}
          </span>
        </span>
      </label>
      <label className="flex items-baseline gap-2">
        <input
          type="radio"
          name={name}
          checked={value.own}
          onChange={() => onChange({ own: true, key: value.key })}
        />
        <span>Use my own key</span>
      </label>
      {value.own && (
        <input
          type="password"
          className="field font-mono text-xs"
          placeholder={`${provider} API key — encrypted, held only while the run executes`}
          value={value.key}
          onChange={(e) => onChange({ own: true, key: e.target.value })}
        />
      )}
    </div>
  );
}
