/* Timestamps from the API are UTC without a zone suffix
   ("2026-09-21T19:14:11.863000"): Mongo stores naive UTC and the JSON
   encoder writes it as-is. A browser reads a zone-less ISO string as
   *local* time, so a run made at 00:44 IST showed as 18:00. Treated as
   UTC here and shown in the viewer's own zone. */
export function whenLocal(iso: string | null | undefined): string {
  if (!iso) return "";
  const utc = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z";
  const d = new Date(utc);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
