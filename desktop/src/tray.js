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

module.exports = { trayModel };
