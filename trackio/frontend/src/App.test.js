import {it, expect, vi} from 'vitest';
import {mount, unmount, tick} from 'svelte';
import App from './App.svelte';
import {buildSnapshot} from './lib/viewState.js';
vi.mock("./components/Navbar.svelte", () => ({default: () => {}}));
const { sidebar } = vi.hoisted(() => ({sidebar: {props: null}}));
vi.mock("./components/Sidebar.svelte", () => ({default: (_anchor, props) => {sidebar.props = props;}}));
vi.mock("./components/AlertPanel.svelte", () => ({default: () => {}}));
vi.mock("./pages/Metrics.svelte", () => ({default: () => {}}));
vi.mock("./pages/Traces.svelte", () => ({default: () => {}}));
vi.mock("./pages/SystemMetrics.svelte", () => ({default: () => {}}));
vi.mock("./pages/Media.svelte", () => ({default: () => {}}));
vi.mock("./pages/Reports.svelte", () => ({default: () => {}}));
vi.mock("./pages/Runs.svelte", () => ({default: () => {}}));
vi.mock("./pages/RunDetail.svelte", () => ({default: () => {}}));
vi.mock("./pages/Files.svelte", () => ({default: () => {}}));
vi.mock("./components/ArtifactsSidebar.svelte", () => ({default: () => {}}));
vi.mock("./pages/ArtifactsDetail.svelte", () => ({default: () => {}}));
vi.mock("./pages/Settings.svelte", () => ({default: () => {}}));
vi.mock('./lib/theme.js', () => ({initTheme:()=>{},isDark:()=>false,onThemeChange:()=>{}}));
vi.mock('./lib/api.js', () => ({
 getAllProjects: async () => ['demo'], getRunsForProject: async () => [{id:'a',name:'train'},{id:'b',name:'eval'}],
 getRunConfigs: async () => ({a:{size:32},b:{size:64}}), getAlerts:async()=>[], getTabAvailability:async()=>({}),
 getRunMutationStatus:async()=>({allowed:true}), getSettings:async()=>({}),getReadOnlySource:async()=>null,
 isStaticMode:async()=>true,setMediaDir:()=>{}
}));
const filters = (value) => [[{key: '["size"]', operator: "=", value}]];
function navigate(name, config, page = "/") {
  const params = new URLSearchParams({project: "demo"});
  if (name) params.set("run_filter", name);
  if (config) params.set("config_filter", JSON.stringify(config));
  window.history.pushState({}, "", `${page}?${params}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
it("restores filters on history navigation without resetting edits on tab changes", async () => {
  vi.stubGlobal("matchMedia", () => ({matches: false, addEventListener() {}, removeEventListener() {}}));
  navigate("train", filters("32"));
  const target = document.createElement("div");
  document.body.append(target);
  const app = mount(App, {target});
  try {
    await vi.waitFor(() => expect(buildSnapshot().runs.map((run) => run.id)).toEqual(["a"]));
    navigate("eval", filters("64"));
    await tick();
    expect(buildSnapshot()).toMatchObject({run_filter: "eval", config_filter: filters("64"), runs: [{id: "b"}]});
    navigate(null, null);
    await tick();
    expect(buildSnapshot()).toMatchObject({run_filter: null, config_filter: []});
    expect(buildSnapshot().runs).toHaveLength(2);
    sidebar.props.filterText = "eval";
    sidebar.props.configFilters = filters("64");
    await tick();
    navigate(null, null, "/runs");
    await tick();
    expect(buildSnapshot()).toMatchObject({run_filter: "eval", config_filter: filters("64"), runs: [{id: "b"}]});
  } finally {
    await unmount(app);
    target.remove();
    vi.unstubAllGlobals();
  }
});
