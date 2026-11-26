const TOOLTIPS = {
  idle: 'Teams Listener — idle',
  nomic: 'Teams Listener — recording Others only (no mic)',
  muted: 'Teams Listener — recording, mic MUTED',
  live: 'Teams Listener — recording, mic LIVE',
};

// state is the engine's last `state` event data (or null before the first one).
function trayModel(state) {
  const rec = !!(state && state.recording);
  const muted = !!(state && state.muted);
  let colour = 'idle';
  if (rec) colour = state.nomic ? 'nomic' : (muted ? 'muted' : 'live');
  return {
    colour,
    tooltip: TOOLTIPS[colour],
    items: [
      { id: 'show', label: 'Show', enabled: true },
      { id: 'startStop', label: rec ? 'Stop recording' : 'Start recording', enabled: true },
      { id: 'mute', label: muted ? 'Unmute mic' : 'Mute mic', enabled: rec },
      { id: 'quit', label: 'Quit', enabled: true },
    ],
  };
}

// Engine lifecycle events that invalidate the last known state: a dead engine is not recording.
function stateAfterEngineEvent(event, last) {
  if (event === 'exit' || event === 'failed') {
    // seq -1: the next engine counts from 0 again, so the windows must not treat its states as stale.
    return { recording: false, muted: true, title: '', folder: null, elapsed_s: 0, nomic: false, seq: -1 };
  }
  return last;
}

module.exports = { trayModel, stateAfterEngineEvent };
