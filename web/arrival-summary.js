// The legacy map passes trusted, bus-level bootstrap values into this module.
// It never requests private intake records or places arrivals on a new map point.
const FIELDS = [
  ["vehicle_id", "Bus"], ["destination_node", "Destination"],
  ["expected_count", "Expected"], ["confirmed_count", "Confirmed"],
  ["difference", "Remaining difference"], ["intake_state", "Intake"],
  ["awaiting_reviews", "Awaiting care review"],
  ["completed_reviews", "Care review actions completed"],
];

function node(tag, value) {
  const item = document.createElement(tag);
  item.textContent = String(value);
  return item;
}

export function mountArrivalSummary(container, summary) {
  if (!(container instanceof Element)) return;
  container.replaceChildren();
  if (!summary || typeof summary !== "object" || Array.isArray(summary)) {
    container.hidden = true;
    return;
  }
  const selected = FIELDS.filter(([key]) => Object.hasOwn(summary, key) &&
    ["string", "number"].includes(typeof summary[key]));
  if (!selected.length) {
    container.hidden = true;
    return;
  }
  const title = node("h3", "Arrival intake · bus summary");
  const provenance = node("p", summary.mode === "exercise" ?
    "Exercise · simulated bus attendance and care workflow" :
    "Provenance unverified · attendance is not verified operational data");
  const list = document.createElement("dl");
  for (const [key, label] of selected) {
    list.append(node("dt", label), node("dd", summary[key]));
  }
  container.append(title, provenance, list);
  container.hidden = false;
}

export function mountConfiguredArrivalIntake(container, configuration) {
  if (!(container instanceof Element)) return;
  container.replaceChildren();
  container.hidden = true;
  if (!configuration || typeof configuration !== "object") return;
  const { entry_url: entry, summary } = configuration;
  if (typeof entry !== "string" || !entry.trim()) return;
  let url;
  try { url = new URL(entry, document.baseURI); } catch { return; }
  // An entry is supplied by trusted deployment configuration, never guessed.
  if (url.origin !== location.origin || !["http:", "https:"].includes(url.protocol) ||
      url.username || url.password || url.search || url.hash ||
      !entry.trim().startsWith("/") && !entry.trim().startsWith(".")) return;
  const link = document.createElement("a");
  link.href = url.href;
  link.textContent = "Open assigned arrival intake";
  container.append(link);
  if (summary && typeof summary === "object") {
    const section = document.createElement("section");
    mountArrivalSummary(section, summary);
    if (!section.hidden) container.append(section);
  }
  container.hidden = false;
}
