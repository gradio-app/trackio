import "./lib/gradio-theme.css";
import App from "./App.svelte";
import RegistryApp from "./RegistryApp.svelte";
import { mount } from "svelte";

const base = window.__trackio_base || "";
const relativePath = window.location.pathname.startsWith(base)
  ? window.location.pathname.slice(base.length)
  : window.location.pathname;
const pathname = relativePath.replace(/\/+$/, "");
const Root = pathname === "/registry" ? RegistryApp : App;
const app = mount(Root, { target: document.getElementById("app") });

export default app;
