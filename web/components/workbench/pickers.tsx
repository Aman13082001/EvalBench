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
  SuiteDoc,
  listProviders,
  ProviderInfo,
} from "@/lib/api";

/* ── Benchmark ──────────────────────────────────────────────────
   "Benchmark" is the word the UI uses; the API says "suite". Three
   sources: the ones EvalBench ships, the user's own, or a YAML file.
   Selection is cheap; resolving to a real suite id (adopting a bundled
   one, importing an upload) only happens when a run actually starts. */

export type BenchmarkChoice =
  | { kind: "bundled"; slug: string; label: string; tests: number; provider: string; model: string }
  | { kind: "mine"; id: string; label: string; tests: number; provider: string; model: string }
  | { kind: "upload"; suite: Record<string, unknown>; label: string; tests: number; provider: string; model: string };

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
              {b.title} · {b.test_count} tests
            </option>
          ))}
        </optgroup>
        {mine.length > 0 && (
          <optgroup label="Your benchmarks">
            {mine.map((s) => (
              <option key={s._id} value={`m:${s._id}`}>
                {s.name} · {s.test_count ?? s.tests?.length ?? 0} tests
              </option>
            ))}
          </optgroup>
        )}
        {value?.kind === "upload" && (
          <option value="upload">
            {value.label} · {value.tests} tests (uploaded)
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
            {value.tests} tests
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
];

export type ModelChoice = { provider: string; model: string };

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

  return (
    <div className="grid gap-2 sm:grid-cols-[11rem_1fr]">
      <select
        id={`${idPrefix}-provider`}
        aria-label="Provider"
        className="field font-mono text-sm"
        value={value.provider}
        onChange={(e) => onChange({ provider: e.target.value, model: "" })}
      >
        {(providers ?? FALLBACK_PROVIDERS).map((p) => (
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
}: {
  value: KeyMode;
  onChange: (k: KeyMode) => void;
  quota: Quota | null;
  provider: string;
  /** Radio group name — must differ per instance on a page, or two
   *  pickers become one group and uncheck each other. */
  name?: string;
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

  const left =
    quota == null
      ? "…"
      : quota.cap == null
        ? "unlimited"
        : `${quota.remaining} of ${quota.cap} left today`;
  const exhausted = quota?.remaining === 0;

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
            · {left}
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
