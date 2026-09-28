// Village configuration. Loads/batteries follow prototype 05 bench loads, dashboard channels,
// household_simulation archetypes (12 V, 150 Ah, 80 % DoD, η 0.85) and V-Guard 80–230 Ah range.
const H = (h, m = 0) => h * 60 + m;

const EVENING = {
  hallTube: [[H(18, 20), H(23, 45)]],
  bedBulb: [[H(18, 45), H(23, 30)]],
  kitBulb: [[H(18, 30), H(21, 15)]],
  fans: [[H(17, 0), H(30, 0)]],
  tv: [[H(19, 30), H(22, 40)]],
  iron: [[H(19, 15), H(19, 35)]],
  ac: [[H(21, 0), H(24, 0)]],
};

const circuitsStd = {
  ch1: { tier: 'T1', label: 'Fridge · router · hall light', locked: true },
  ch2: { tier: 'T2', label: 'Fans · TV · room lights' },
  ch3: { tier: 'T3', label: 'Heavy sockets (iron)' },
  ch4: { tier: 'MED', label: 'Medical socket', locked: true },
};

const familyLoads = (phase = 0) => [
  { id: 'fridge', kind: 'fridge', room: 'kitchen', circuit: 'ch1', sched: { duty: [15, 15, phase] } },
  { id: 'router', kind: 'router', room: 'utility', circuit: 'ch1', sched: 'always' },
  { id: 'hallTube', kind: 'tube', room: 'hall', circuit: 'ch1', sched: EVENING.hallTube },
  { id: 'hallFan', kind: 'fan', room: 'hall', circuit: 'ch2', sched: EVENING.fans },
  { id: 'bedFan', kind: 'fan', room: 'bed', circuit: 'ch2', sched: EVENING.fans },
  { id: 'tv', kind: 'tv', room: 'hall', circuit: 'ch2', sched: EVENING.tv },
  { id: 'bedBulb', kind: 'bulb', room: 'bed', circuit: 'ch2', sched: EVENING.bedBulb },
  { id: 'kitBulb', kind: 'bulb', room: 'kitchen', circuit: 'ch2', sched: EVENING.kitBulb },
  { id: 'iron', kind: 'iron', room: 'utility', circuit: 'ch3', sched: EVENING.iron },
  { id: 'ac', kind: 'ac', room: 'bed', circuit: 'NI', sched: EVENING.ac },
];

export const VILLAGE_HOUSES = [
  {
    id: 'h1', name: 'Home 1 · Family', short: 'Home 1', sentinel: true,
    ah: 150, soh: 0.93, gradeIdx: 1, soc0: 0.94,
    pos: [-18, 0, -12], rot: 0, style: 'hip', wall: '#F3E7C9', roof: '#B4502F', trim: '#7A3E26',
    circuits: circuitsStd, appliances: familyLoads(0),
  },
  {
    id: 'h2', name: 'Home 2 · Elderly care', short: 'Home 2', sentinel: true,
    ah: 150, soh: 0.83, gradeIdx: 2, soc0: 0.92,
    pos: [0, 0, -12], rot: 0, style: 'flat', wall: '#CDEBD9', roof: '#E9E4DA', trim: '#4F7F68',
    circuits: { ...circuitsStd, ch4: { tier: 'MED', label: 'Medical socket (CPAP)', locked: true } },
    appliances: [
      { id: 'fridge', kind: 'fridge', room: 'kitchen', circuit: 'ch1', sched: { duty: [15, 15, 7] } },
      { id: 'router', kind: 'router', room: 'utility', circuit: 'ch1', sched: 'always' },
      { id: 'hallTube', kind: 'tube', room: 'hall', circuit: 'ch1', sched: EVENING.hallTube },
      { id: 'hallFan', kind: 'fan', room: 'hall', circuit: 'ch2', sched: EVENING.fans },
      { id: 'bedFan', kind: 'fan', room: 'bed', circuit: 'ch2', sched: EVENING.fans },
      { id: 'tv', kind: 'tv', room: 'hall', circuit: 'ch2', sched: EVENING.tv },
      { id: 'bedBulb', kind: 'bulb', room: 'bed', circuit: 'ch2', sched: EVENING.bedBulb },
      { id: 'kitBulb', kind: 'bulb', room: 'kitchen', circuit: 'ch2', sched: EVENING.kitBulb },
      { id: 'cpap', kind: 'cpap', room: 'bed', circuit: 'ch4', sched: [[H(21, 30), H(30, 0)]] },
    ],
  },
  {
    id: 'h3', name: 'Home 3 · Small flat', short: 'Home 3', sentinel: true,
    ah: 100, soh: 0.95, gradeIdx: 1, soc0: 0.96,
    pos: [18, 0, -12], rot: 0, style: 'hip', wall: '#F6D3B8', roof: '#A8472B', trim: '#8C4A2F',
    circuits: circuitsStd,
    appliances: [
      { id: 'fridge', kind: 'fridge', room: 'kitchen', circuit: 'ch1', sched: { duty: [12, 18, 3] }, w: 90, q: 70 },
      { id: 'router', kind: 'router', room: 'utility', circuit: 'ch1', sched: 'always' },
      { id: 'hallTube', kind: 'tube', room: 'hall', circuit: 'ch1', sched: EVENING.hallTube },
      { id: 'hallFan', kind: 'fan', room: 'hall', circuit: 'ch2', sched: EVENING.fans },
      { id: 'bedFan', kind: 'fan', room: 'bed', circuit: 'ch2', sched: [[H(21, 0), H(30, 0)]] },
      { id: 'tv', kind: 'tv', room: 'hall', circuit: 'ch2', sched: EVENING.tv },
      { id: 'bedBulb', kind: 'bulb', room: 'bed', circuit: 'ch2', sched: EVENING.bedBulb },
    ],
  },
  {
    id: 'h4', name: 'Home 4 · Home office', short: 'Home 4', sentinel: true,
    ah: 180, soh: 0.93, gradeIdx: 1, soc0: 0.95,
    pos: [-18, 0, 12], rot: Math.PI, style: 'flat', wall: '#CFE3F5', roof: '#E6E2DA', trim: '#3E6A8F',
    circuits: { ...circuitsStd, ch1: { tier: 'T1', label: 'Fridge · router · laptop · hall light', locked: true } },
    appliances: [
      { id: 'fridge', kind: 'fridge', room: 'kitchen', circuit: 'ch1', sched: { duty: [15, 15, 11] } },
      { id: 'router', kind: 'router', room: 'utility', circuit: 'ch1', sched: 'always' },
      { id: 'laptop', kind: 'laptop', room: 'utility', circuit: 'ch1', sched: [[H(17, 0), H(22, 30)]] },
      { id: 'hallTube', kind: 'tube', room: 'hall', circuit: 'ch1', sched: EVENING.hallTube },
      { id: 'hallFan', kind: 'fan', room: 'hall', circuit: 'ch2', sched: EVENING.fans },
      { id: 'bedFan', kind: 'fan', room: 'bed', circuit: 'ch2', sched: EVENING.fans },
      { id: 'tv', kind: 'tv', room: 'hall', circuit: 'ch2', sched: [[H(21, 0), H(23, 0)]] },
      { id: 'bedBulb', kind: 'bulb', room: 'bed', circuit: 'ch2', sched: EVENING.bedBulb },
      { id: 'kitBulb', kind: 'bulb', room: 'kitchen', circuit: 'ch2', sched: EVENING.kitBulb },
      { id: 'ac', kind: 'ac', room: 'bed', circuit: 'NI', sched: EVENING.ac },
    ],
  },
  {
    id: 'h5', name: 'Home 5 · Ageing battery', short: 'Home 5', sentinel: true,
    ah: 150, soh: 0.68, gradeIdx: 3, soc0: 0.9,
    pos: [0, 0, 12], rot: Math.PI, style: 'hip', wall: '#E3D7F1', roof: '#9E4A32', trim: '#6B4F8A',
    circuits: circuitsStd, appliances: familyLoads(5),
  },
  {
    id: 'h6', name: 'Home 6 · Same as Home 1, no Sentinel', short: 'Home 6', sentinel: false,
    ah: 150, soh: 0.93, gradeIdx: 1, soc0: 0.94,
    pos: [18, 0, 12], rot: Math.PI, style: 'hip', wall: '#F4EDB5', roof: '#B4502F', trim: '#8A7A2A',
    circuits: circuitsStd, appliances: familyLoads(0),
  },
];

export const VILLAGE_OUTAGES = [[H(19, 0), H(23, 0)]]; // 4 h evening outage (8 × 4 h / month default)
export const VILLAGE_T0 = H(18, 40) * 60;
