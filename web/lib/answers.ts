/* Read a file of answers the visitor already has.

   Mirrors evalbench/answers.py: the same three formats and the same
   lenient column names, so a file that parses here parses there. The
   server re-validates regardless — this exists so a typo is caught
   before a request, with the row named, not after a run has been queued. */

export interface AnswerRow {
  test_name: string | null;
  prompt: string | null;
  response: string;
}

const RESPONSE_KEYS = ["response", "answer", "output", "completion", "text"];
const NAME_KEYS = ["test_name", "test", "name", "id"];
const PROMPT_KEYS = ["prompt", "input", "question"];

function first(row: Record<string, unknown>, keys: string[]): string | null {
  for (const k of keys) {
    const v = row[k];
    if (v !== undefined && v !== null && String(v).trim() !== "") return String(v);
  }
  return null;
}

/* A small RFC 4180 reader: quoted fields, doubled quotes, newlines inside
   quotes. Enough for what spreadsheets export. */
function parseCsv(text: string, delimiter: string): Record<string, string>[] {
  const rows: string[][] = [];
  let field = "";
  let row: string[] = [];
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else inQuotes = false;
      } else field += c;
    } else if (c === '"') inQuotes = true;
    else if (c === delimiter) {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else field += c;
  }
  if (field !== "" || row.length) {
    row.push(field);
    rows.push(row);
  }
  const [header, ...body] = rows.filter((r) => r.some((x) => x.trim() !== ""));
  if (!header) return [];
  const keys = header.map((h) => h.trim());
  return body.map((r) => Object.fromEntries(keys.map((k, i) => [k, r[i] ?? ""])));
}

function rowsFrom(text: string, filename: string): Record<string, unknown>[] {
  const s = text.trim();
  if (!s) throw new Error("No answers found — the file is empty.");

  if (s.startsWith("[")) {
    const data = JSON.parse(s);
    if (!Array.isArray(data)) throw new Error("Expected a JSON array of objects.");
    return data.filter((d) => d && typeof d === "object");
  }

  if (s.startsWith("{")) {
    return s
      .split(/\r?\n/)
      .map((line, i) => [line.trim(), i + 1] as const)
      .filter(([line]) => line)
      .map(([line, n]) => {
        try {
          return JSON.parse(line);
        } catch {
          throw new Error(`Line ${n} is not valid JSON.`);
        }
      });
  }

  const lower = filename.toLowerCase();
  const firstLine = s.split(/\r?\n/)[0] ?? "";
  if (lower.endsWith(".csv") || lower.endsWith(".tsv") || firstLine.includes(",")) {
    return parseCsv(s, lower.endsWith(".tsv") ? "\t" : ",");
  }

  throw new Error(
    "Could not read this as JSON, JSON Lines or CSV. Each answer needs a `response` and either a `test_name` or a `prompt`."
  );
}

export function parseAnswers(text: string, filename = ""): AnswerRow[] {
  const rows = rowsFrom(text, filename);
  if (!rows.length) throw new Error("No answers found in the file.");
  return rows.map((row, i) => {
    const response = first(row, RESPONSE_KEYS);
    if (response === null)
      throw new Error(
        `Answer ${i + 1} has no response (looked for one of ${RESPONSE_KEYS.join(", ")}).`
      );
    const test_name = first(row, NAME_KEYS);
    const prompt = first(row, PROMPT_KEYS);
    if (test_name === null && prompt === null)
      throw new Error(
        `Answer ${i + 1} has neither a test_name nor a prompt, so there is no way to tell which test it answers.`
      );
    return { test_name, prompt, response };
  });
}
