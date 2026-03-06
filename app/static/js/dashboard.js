/* ICC AI Agent — Dashboard JS */

function toggleLaneDropdown() {
  const menu = document.getElementById('lane-dropdown-menu');
  const btn = document.getElementById('lane-dropdown-btn');
  const open = menu.classList.toggle('open');
  btn.classList.toggle('open', open);
}

function updateLaneLabel() {
  const checked = Array.from(document.querySelectorAll('input[name="port_pair"]:checked'));
  const label = document.getElementById('lane-dropdown-label');
  if (checked.length === 0) {
    label.textContent = 'Select port pairs…';
  } else {
    // Group by lane for compact label
    const byLane = {};
    checked.forEach(el => {
      const [lane, origin, dest] = el.value.split('|');
      if (!byLane[lane]) byLane[lane] = [];
      byLane[lane].push(dest);
    });
    label.textContent = Object.entries(byLane)
      .map(([lane, dests]) => `${lane}: ${dests.join(', ')}`)
      .join(' · ');
  }
}

function selectAllInGroup(laneKey, event) {
  event.stopPropagation();
  const checkboxes = document.querySelectorAll(`input[name="port_pair"][data-lane="${laneKey}"]`);
  const allChecked = Array.from(checkboxes).every(cb => cb.checked);
  checkboxes.forEach(cb => cb.checked = !allChecked);
  updateLaneLabel();
}

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
  const wrap = document.getElementById('lane-dropdown-wrap');
  if (wrap && !wrap.contains(e.target)) {
    document.getElementById('lane-dropdown-menu')?.classList.remove('open');
    document.getElementById('lane-dropdown-btn')?.classList.remove('open');
  }
});


async function triggerRun() {
  const btn = document.getElementById('run-btn');
  const btnText = document.getElementById('run-btn-text');
  const status = document.getElementById('run-status');
  const extraContext = document.getElementById('extra-context').value.trim();
  const checkedPairs = Array.from(document.querySelectorAll('input[name="port_pair"]:checked'));

  if (checkedPairs.length === 0) {
    status.className = 'run-status err';
    status.textContent = 'Select at least one port pair.';
    return;
  }

  // Derive unique trade lanes from selected port pairs
  const lanes = [...new Set(checkedPairs.map(el => el.value.split('|')[0]))];
  const portPairs = checkedPairs.map(el => {
    const [lane, origin, dest] = el.value.split('|');
    return { lane, origin, dest };
  });

  btn.disabled = true;
  btnText.textContent = 'Running agent…';
  status.className = 'run-status info';
  status.textContent = `Collecting signals for ${lanes.join(' + ')}… This may take 30–60 seconds.`;

  try {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ extra_context: extraContext, trigger: 'manual', trade_lanes: lanes, port_pairs: portPairs }),
    });
    const data = await res.json();

    if (data.status === 'ok') {
      status.className = 'run-status ok';
      status.innerHTML = `Run #${data.run_id} complete. <a href="${data.view_url}" style="color:inherit;font-weight:700;">View briefing &rarr;</a>`;
      btnText.textContent = 'Generate ICC Briefing';
      btn.disabled = false;
      // Reload after a short pause so dashboard updates
      setTimeout(() => { window.location.reload(); }, 1500);
    } else {
      throw new Error(data.error || 'Unknown error');
    }
  } catch (err) {
    status.className = 'run-status err';
    status.textContent = 'Error: ' + err.message;
    btnText.textContent = 'Generate ICC Briefing';
    btn.disabled = false;
  }
}

async function submitSignal() {
  const author = document.getElementById('sig-author').value.trim();
  const text = document.getElementById('sig-text').value.trim();
  const tags = document.getElementById('sig-tags').value.trim();
  const status = document.getElementById('sig-status');

  if (!text) {
    status.className = 'run-status err';
    status.textContent = 'Signal text is required.';
    return;
  }

  try {
    const res = await fetch('/api/signal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ author: author || 'Anonymous', text, tags }),
    });
    const data = await res.json();

    if (data.status === 'ok') {
      status.className = 'run-status ok';
      status.textContent = 'Signal added.';
      document.getElementById('sig-text').value = '';
      document.getElementById('sig-tags').value = '';
      // Reload to show new signal in list
      setTimeout(() => { window.location.reload(); }, 800);
    } else {
      throw new Error(data.error || 'Unknown error');
    }
  } catch (err) {
    status.className = 'run-status err';
    status.textContent = 'Error: ' + err.message;
  }
}
