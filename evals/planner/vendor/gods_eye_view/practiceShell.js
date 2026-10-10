import { createRailTimeline } from './railTimeline.js';
import { resolveHudRailLayout } from './panelRailGeometry.js';
import { allocatePanelStackHeights } from './panelStackLayout.js';

const SVG = 'http://www.w3.org/2000/svg';
const byId = (doc, id) => doc.getElementById(id);
const label = (value) => String(value ?? '—');
const list = (value) => Array.isArray(value) ? value : [];
const elapsed = (seconds) => {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  return String(Math.floor(value / 60)) + ':' + String(value % 60).padStart(2, '0');
};
const element = (doc, tag, text, className) => {
  const node = doc.createElement(tag);
  if (text !== undefined) node.textContent = label(text);
  if (className) node.className = className;
  return node;
};
const clear = (node) => node.replaceChildren();
const svg = (doc, tag, attributes) => {
  const node = doc.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
  return node;
};
function fact(doc, title, value) {
  const row = element(doc, 'div', undefined, 'fact');
  row.append(element(doc, 'strong', title), element(doc, 'span', value));
  return row;
}
function requestText(item) {
  return label(item.id) + ' · ' + label(item.kind) + ' · ' +
    label(item.remaining ?? item.quantity) + ' remaining · ' + label(item.node_id);
}
function actionText(action) {
  return label(action.explanation || action.label || action.kind || action.id);
}
function renderGraph(doc, target, knowledge) {
  clear(target);
  const nodes = list(knowledge.nodes);
  const roads = list(knowledge.roads);
  if (!nodes.length) {
    target.setAttribute('aria-label', 'No network geometry received');
    return;
  }
  const xs = nodes.map((n) => Number(n.x_m)).filter(Number.isFinite);
  const ys = nodes.map((n) => Number(n.y_m)).filter(Number.isFinite);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  // Fit current geometry into the unobstructed centre, clear of rails, title, and dock.
  const rect = target.getBoundingClientRect();
  const mobile = doc.defaultView?.innerWidth <= 900;
  const viewWidth = mobile ? Math.max(320, rect.width) : 1000;
  const viewHeight = mobile ? Math.max(300, rect.height) : 700;
  target.setAttribute('viewBox', '0 0 ' + viewWidth + ' ' + viewHeight);
  const scale = Math.min(rect.width / viewWidth, rect.height / viewHeight);
  let minPlotX = mobile ? 30 : 245;
  let maxPlotX = mobile ? viewWidth - 65 : 755;
  let minPlotY = mobile ? 75 : 205;
  let maxPlotY = mobile ? viewHeight - 35 : 520;
  if (Number.isFinite(scale) && scale > 0) {
    const letterX = (rect.width - viewWidth * scale) / 2;
    const letterY = (rect.height - viewHeight * scale) / 2;
    const toX = (pixel) => (pixel - rect.left - letterX) / scale;
    const toY = (pixel) => (pixel - rect.top - letterY) / scale;
    const title = byId(doc, 'stage-title')?.getBoundingClientRect();
    const dock = byId(doc, 'mission-dock')?.getBoundingClientRect();
    const legend = byId(doc, 'stage-key')?.getBoundingClientRect();
    const left = byId(doc, 'left-panel-stack')?.getBoundingClientRect();
    const right = byId(doc, 'right-context-rail')?.getBoundingClientRect();
    const desktop = doc.defaultView?.innerWidth > 900;
    const leftEdge = desktop && left ? left.right + 35 : rect.left + 30;
    const rightEdge = desktop && right ? right.left - 65 : rect.right - 65;
    const topEdge = title ? title.bottom + 28 : rect.top + 80;
    const dockEdge = dock && dock.top < rect.bottom ? dock.top - 35 : rect.bottom - 35;
    const bottomEdge = legend ? Math.min(dockEdge, legend.top - 30) : dockEdge;
    const bounds = [toX(leftEdge), toX(rightEdge), toY(topEdge), toY(bottomEdge)];
    if (bounds.every(Number.isFinite) && bounds[1] - bounds[0] >= 120 &&
        bounds[3] - bounds[2] >= 100) {
      [minPlotX, maxPlotX, minPlotY, maxPlotY] = bounds;
    }
  }
  const point = (node) => ({
    x: minPlotX + (Number(node.x_m) - minX) / Math.max(1, maxX - minX) * (maxPlotX - minPlotX),
    y: minPlotY + (Number(node.y_m) - minY) / Math.max(1, maxY - minY) * (maxPlotY - minPlotY),
  });
  const positions = new Map(nodes.map((n) => [n.id, point(n)]));
  const closures = new Set(list(knowledge.observations)
    .filter((o) => o.kind === 'road_closed').map((o) => o.edge_id));
  const resources = new Set(list(knowledge.resources).map((r) => r.node_id));
  const facilities = new Set(list(knowledge.facilities).map((f) => f.node_id));
  const seen = new Set();
  for (const road of roads) {
    const from = positions.get(road.source), to = positions.get(road.target);
    if (!from || !to) continue;
    const key = label(road.physical_id || [road.source, road.target].sort().join(':'));
    if (seen.has(key)) continue;
    seen.add(key);
    const related = roads.filter((r) => label(r.physical_id || [r.source, r.target].sort().join(':')) === key);
    const closed = related.some((r) => closures.has(r.id));
    const line = svg(doc, 'line', {
      x1: from.x, y1: from.y, x2: to.x, y2: to.y,
      stroke: closed ? '#fa7372' : '#409eaf',
      'stroke-width': closed ? 3 : 2, 'stroke-opacity': closed ? 0.95 : 0.55,
      'stroke-dasharray': closed ? '7 5' : '',
    });
    target.appendChild(line);
  }
  for (const node of nodes) {
    const pos = positions.get(node.id);
    const facility = facilities.has(node.id);
    const resource = resources.has(node.id);
    target.appendChild(svg(doc, 'circle', {
      cx: pos.x, cy: pos.y, r: resource ? 9 : 6,
      fill: resource ? '#faf6d6' : facility ? '#f8b86b' : '#63dae5',
      stroke: '#071923', 'stroke-width': 2,
    }));
    const text = svg(doc, 'text', {
      x: pos.x + 11, y: pos.y - 9, fill: '#d3edf0', 'font-size': 13,
      'font-family': 'system-ui, sans-serif',
    });
    text.textContent = label(node.id);
    target.appendChild(text);
  }
  target.setAttribute('aria-label',
    'Current known synthetic graph: ' + nodes.length + ' nodes, ' +
    seen.size + ' road links, ' + closures.size + ' received closures');
}
function renderDebrief(doc, target, debrief, thinking, choiceTimes) {
  clear(target);
  target.hidden = false;
  target.appendChild(element(doc, 'h2', 'Mission debrief'));
  target.appendChild(element(doc, 'p', debrief.scope ||
    'Synthetic outcome; no real-world performance improvement is established.'));
  target.appendChild(element(doc, 'p',
    'Browser thinking time: ' + thinking.toFixed(1) + ' s total; this did not affect simulation.'));
  const metrics = debrief.metrics || {};
  const comparison = debrief.comparison || {};
  const table = element(doc, 'table');
  const head = element(doc, 'tr');
  for (const title of ['Counter', 'Your mission', 'Situational', 'Priority greedy']) {
    head.appendChild(element(doc, 'th', title));
  }
  table.appendChild(head);
  for (const [key, value] of Object.entries(metrics)) {
    const row = element(doc, 'tr');
    for (const cell of [key.replaceAll('_', ' '), value,
      comparison.situational?.[key] ?? '—', comparison.priority_greedy?.[key] ?? '—']) {
      row.appendChild(element(doc, 'td', cell));
    }
    table.appendChild(row);
  }
  target.appendChild(table);
  const title = element(doc, 'h3', 'Review prompts');
  target.appendChild(title);
  const prompts = element(doc, 'ul');
  for (const prompt of list(debrief.critique_prompts)) prompts.appendChild(element(doc, 'li', prompt));
  target.appendChild(prompts);
  const breakdown = element(doc, 'details');
  breakdown.appendChild(element(doc, 'summary', 'Per-choice thinking time'));
  const choices = element(doc, 'ol');
  for (const entry of choiceTimes) {
    choices.appendChild(element(doc, 'li',
      label(entry.actionId) + ' · ' + entry.seconds.toFixed(1) + ' s'));
  }
  breakdown.appendChild(choices);
  target.appendChild(breakdown);
}
export function mountPracticeShell({ document = globalThis.document, fetcher = globalThis.fetch, readOnly = false } = {}) {
  if (!document?.getElementById || typeof fetcher !== 'function') return null;
  const root = byId(document, 'practice-root');
  if (!root || !byId(document, 'mission-network') || !byId(document, 'mission-timeline')) return null;
  const fields = Object.fromEntries([
    'connection-status', 'mission-network', 'stage-title', 'scenario-content',
    'layers-content', 'display-content', 'controls-content', 'mission-clock',
    'thinking-time', 'debrief-panel', 'notice', 'practice-mode', 'review-mode',
    'left-panel-stack', 'right-context-rail', 'title-bar', 'mission-dock',
  ].map((id) => [id, byId(document, id)]));
  if (Object.values(fields).some((value) => !value)) return null;
  let meta = null, session = null, current = null, episodeIndex = 0;
  let history = [], historyIndex = 0, review = false, pending = false;
  let decisionStartedAt = null, decisionAccumMs = 0, thinkingTotal = 0, playing = null;
  let choiceTimes = [];
  const clock = () => globalThis.performance?.now?.() ?? Date.now();
  const decisionMs = () => decisionAccumMs +
    (decisionStartedAt === null ? 0 : Math.max(0, clock() - decisionStartedAt));
  const pauseDecisionClock = () => {
    const duration = decisionMs();
    decisionAccumMs = duration;
    decisionStartedAt = null;
    return duration / 1000;
  };
  const resumeDecisionClock = () => {
    if (!readOnly && decisionStartedAt === null && current && !current.debrief && !pending && !review) {
      decisionStartedAt = clock();
    }
  };
  const recordChoice = (actionId, seconds) => {
    choiceTimes.push({ actionId, seconds });
    thinkingTotal += seconds;
    decisionAccumMs = 0;
    decisionStartedAt = null;
  };
  const updateThinkingDisplay = () => {
    if (!current) return;
    const strong = fields['thinking-time'].querySelector('strong');
    const small = fields['thinking-time'].querySelector('small');
    if (!strong || !small) return;
    const currentSeconds = !review && !current.debrief ? decisionMs() / 1000 : 0;
    strong.textContent = pending ? 'Submitting choice…' : review
      ? 'Recorded decision ' + historyIndex : current.debrief ? 'Mission complete'
      : 'Decision ' + (current.depth + 1) + ' · ' + currentSeconds.toFixed(1) + ' s';
    const selected = review && historyIndex > 0 ? choiceTimes[historyIndex - 1] : choiceTimes.at(-1);
    small.textContent = 'Total ' + thinkingTotal.toFixed(1) + ' s · ' +
      (selected ? 'last choice ' + selected.seconds.toFixed(1) + ' s' : 'no choice yet') +
      ' · browser only';
  };
  const showNotice = (message) => {
    fields.notice.textContent = label(message);
    fields.notice.hidden = false;
  };
  const hideNotice = () => { fields.notice.hidden = true; };
  const request = async (path, body) => {
    const response = await fetcher(path, {
      method: body ? 'POST' : 'GET',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const value = await response.json();
    if (!response.ok) {
      const error = new Error(value.error || 'HTTP ' + response.status);
      error.status = response.status;
      throw error;
    }
    return value;
  };
  const stopReplay = () => {
    if (playing !== null) globalThis.clearInterval(playing);
    playing = null;
  };
  const activeSnapshot = () => review ? history[historyIndex] : current;
  const timeline = createRailTimeline({
    container: byId(document, 'mission-timeline'), document, heading: true,
    onCommit: (_tick, index) => { pauseDecisionClock(); review = true; historyIndex = index; stopReplay(); render(); },
    onPreview: (tick) => 'Simulated mission ' + elapsed(tick),
    onStep: (direction) => {
      pauseDecisionClock(); review = true;
      historyIndex = Math.max(0, Math.min(history.length - 1, historyIndex + direction));
      render();
    },
    onLatest: () => { review = false; historyIndex = history.length - 1; stopReplay(); resumeDecisionClock(); render(); },
    onPlay: () => {
      if (playing !== null) { stopReplay(); render(); return; }
      pauseDecisionClock(); review = true;
      historyIndex = 0;
      playing = globalThis.setInterval(() => {
        if (historyIndex >= history.length - 1) { stopReplay(); render(); return; }
        historyIndex += 1;
        render();
      }, 650);
      render();
    },
  });
  const railLayout = () => {
    const win = document.defaultView;
    if (!win || win.innerWidth <= 900) return;
    const viewportHeight = win.innerHeight;
    const title = fields['title-bar'].getBoundingClientRect();
    const dock = fields['mission-dock'].getBoundingClientRect();
    for (const railId of ['left-panel-stack', 'right-context-rail']) {
      const rail = fields[railId];
      const lane = rail.getBoundingClientRect();
      const panels = Array.from(rail.querySelectorAll('.panel:not(.collapsed)'));
      const natural = panels.map((panel) => Math.max(42,
        panel.querySelector('.panel-heading').scrollHeight +
        panel.querySelector('.panel-body').scrollHeight + 2));
      const slot = resolveHudRailLayout({
        viewportHeight, panelHeight: natural.reduce((a, b) => a + b, 0) + 9,
        laneLeft: lane.left, laneRight: lane.right, baseTop: title.bottom + 15,
        baseBottom: dock.top - 15, align: 'start',
      });
      if (!slot) continue;
      rail.style.top = slot.top + 'px';
      rail.style.bottom = 'auto';
      rail.style.maxHeight = slot.maxHeight + 'px';
      const allocated = allocatePanelStackHeights({
        naturalHeights: natural, availableHeight: Math.max(0, slot.maxHeight - 9 * Math.max(0, panels.length - 1)),
        minimumHeight: 80,
      });
      panels.forEach((panel, index) => { panel.style.maxHeight = Math.max(42, allocated[index]) + 'px'; });
    }
  };
  function render() {
    if (!meta || !current) return;
    const node = activeSnapshot();
    if (!node) return;
    const known = node.knowledge || {};
    fields['connection-status'].textContent =
      (meta.mode === 'live_full_mission' ? 'Full mission' : 'Finite demonstration') +
      ' · ' + (node.depth ?? 0) + '/' + (meta.limits?.decision_limit ?? '?');
    fields['stage-title'].textContent = review
      ? 'Review recorded state · ' + elapsed(node.time_s)
      : 'Current received network · ' + elapsed(node.time_s);
    renderGraph(document, fields['mission-network'], known);
    clear(fields['scenario-content']);
    fields['scenario-content'].append(
      fact(document, 'Episode', meta.episodes[episodeIndex]?.name),
      fact(document, 'Hazard level', known.severity ?? '—'),
      fact(document, 'Mission time', elapsed(node.time_s)),
      fact(document, 'Goals', list(known.goals?.priority_order).join(' → ') || 'See instructor setup'),
      fact(document, 'Supply stock', known.stocks?.supplies ?? '—'),
    );
    const requests = list(known.requests);
    fields['scenario-content'].appendChild(fact(document, 'Received needs', requests.length));
    const requestList = element(document, 'ul', undefined, 'small-list');
    for (const item of requests) requestList.appendChild(element(document, 'li', requestText(item)));
    fields['scenario-content'].appendChild(requestList);
    clear(fields['layers-content']);
    const observations = list(known.observations);
    fields['layers-content'].append(
      fact(document, 'Received reports', observations.length),
      fact(document, 'Known resources', list(known.resources).map((r) =>
        label(r.id) + ' · ' + label(r.status) + ' at ' + label(r.node_id)).join('; ') || 'None'),
      fact(document, 'Known facilities', list(known.facilities).map((f) =>
        label(f.id) + (f.failed ? ' · failed' : ' · available')).join('; ') || 'None'),
    );
    const reportList = element(document, 'ul', undefined, 'small-list');
    for (const report of observations.slice(-8)) {
      reportList.appendChild(element(document, 'li',
        label(report.kind) + ' · ' + label(report.edge_id || report.request?.id || report.facility_id || report.id || '') +
        ' · received ' + elapsed(report.received_at_s)));
    }
    fields['layers-content'].appendChild(reportList);
    clear(fields['display-content']);
    fields['display-content'].appendChild(fact(document, 'Episodes', meta.episodes.length));
    meta.episodes.forEach((episode, index) => {
      const button = element(document, 'button', episode.name, 'episode-btn');
      button.type = 'button';
      button.setAttribute('aria-current', String(index === episodeIndex));
      button.disabled = pending || readOnly;
      button.addEventListener('click', () => start(index));
      fields['display-content'].appendChild(button);
    });
    const restart = element(document, 'button', 'Restart episode', 'minor-btn');
    restart.type = 'button'; restart.disabled = pending || readOnly;
    restart.addEventListener('click', () => start(episodeIndex));
    fields['display-content'].appendChild(restart);
    const details = element(document, 'details');
    details.appendChild(element(document, 'summary', 'Instructor assumptions and 1–10 hazard scale'));
    const assumption = known.assumptions || {};
    for (const [key, value] of Object.entries(assumption)) {
      details.appendChild(fact(document, key.replaceAll('_', ' '), JSON.stringify(value)));
    }
    for (const entry of list(meta.severity_scale)) {
      details.appendChild(fact(document, 'Level ' + label(entry.level), entry.description));
    }
    fields['display-content'].appendChild(details);
    clear(fields['controls-content']);
    if (review) {
      fields['controls-content'].appendChild(fact(document, 'Review', 'Only already received decision states are available. Select Practice to continue.'));
    } else if (node.debrief) {
      fields['controls-content'].appendChild(fact(document, 'Mission complete', 'Open the debrief in the centre.'));
    } else {
      fields['controls-content'].appendChild(fact(document, 'Choose one action', 'The mission advances 15 simulated seconds per decision.'));
      for (const action of list(node.actions)) {
        const button = element(document, 'button', undefined, 'action-btn');
        button.type = 'button';
        const heading = element(document, 'strong', action.kind || action.id);
        button.append(heading, element(document, 'span', actionText(action)));
        button.disabled = readOnly || pending || action.feasible === false || action.supported === false;
        button.addEventListener('click', () => step(action.id));
        fields['controls-content'].appendChild(button);
      }
    }
    fields['mission-clock'].replaceChildren(element(document, 'small', 'Mission clock'),
      document.createTextNode(elapsed(node.time_s)));
    fields['thinking-time'].replaceChildren(
      element(document, 'strong', ''),
      element(document, 'small', ''),
    );
    updateThinkingDisplay();
    fields['practice-mode'].setAttribute('aria-selected', String(!review));
    fields['review-mode'].setAttribute('aria-selected', String(review));
    fields['debrief-panel'].hidden = !node.debrief || review;
    if (node.debrief && !review) renderDebrief(document, fields['debrief-panel'], node.debrief, thinkingTotal, choiceTimes);
    timeline?.update({
      ticks: history.map((entry) => entry.time_s), index: review ? historyIndex : history.length - 1,
      mode: review ? 'review' : 'latest', playing: playing !== null,
      readout: 'Simulated mission ' + elapsed(node.time_s),
      disabled: history.length < 2,
    });
    railLayout();
  }
  async function start(index) {
    if (pending || !meta) return;
    pending = true;
    decisionStartedAt = null;
    hideNotice();
    stopReplay();
    try {
      const response = await request('/start', { episode_index: index });
      session = response.session;
      current = response.node;
      episodeIndex = index;
      history = [current];
      historyIndex = 0;
      review = false;
      thinkingTotal = 0;
      choiceTimes = [];
      decisionAccumMs = 0;
      decisionStartedAt = readOnly ? null : clock();
    } catch (error) {
      showNotice('Could not open exercise: ' + error.message);
    } finally {
      pending = false;
      resumeDecisionClock();
      render();
    }
  }
  async function step(actionId) {
    if (readOnly || pending || review || !session || !current || current.debrief) return;
    const choiceDuration = pauseDecisionClock();
    pending = true;
    const nonce = current.decision_nonce;
    render();
    try {
      const response = await request('/step', {
        session, decision_nonce: nonce, action_id: actionId,
      });
      current = response.node;
      history.push(current);
      historyIndex = history.length - 1;
      recordChoice(actionId, choiceDuration);
      hideNotice();
    } catch (error) {
      try {
        const recovered = await request('/current', { session });
        if (recovered.node.decision_nonce !== nonce) {
          current = recovered.node;
          history.push(current);
          historyIndex = history.length - 1;
          recordChoice(actionId, choiceDuration);
          hideNotice();
        } else {
          showNotice('Choice was not applied: ' + error.message);
        }
      } catch (recoveryError) {
        showNotice('Could not restore current decision: ' + recoveryError.message);
      }
    } finally {
      pending = false;
      resumeDecisionClock();
      render();
    }
  }
  for (const railId of ['left-panel-stack', 'right-context-rail']) {
    fields[railId].querySelectorAll('.panel-heading').forEach((button) => {
      button.addEventListener('click', () => {
        const panel = button.parentElement;
        const collapsed = panel.classList.toggle('collapsed');
        button.setAttribute('aria-expanded', String(!collapsed));
        railLayout();
      });
    });
  }
  fields['practice-mode'].addEventListener('click', () => {
    review = false; stopReplay(); resumeDecisionClock(); render();
  });
  fields['review-mode'].addEventListener('click', () => {
    pauseDecisionClock(); review = true; historyIndex = Math.max(0, history.length - 1); stopReplay(); render();
  });
  document.defaultView?.addEventListener('resize', () => {
    if (current) render(); else railLayout();
  });
  if (!readOnly) globalThis.setInterval(updateThinkingDisplay, 200);
  request('/meta').then((value) => {
    meta = value;
    if (!list(meta.episodes).length) throw new Error('No episodes available');
    return start(0);
  }).catch((error) => showNotice('Could not open exercise: ' + error.message));
  return { getCurrent: () => current, getHistory: () => [...history], restart: () => start(episodeIndex) };
}
if (!globalThis.document?.documentElement?.hasAttribute('data-practice-preview') &&
    globalThis.document?.getElementById?.('practice-root')) mountPracticeShell();
