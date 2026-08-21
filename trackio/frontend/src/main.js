import "./lib/gradio-theme.css";
import App from "./App.svelte";
import RegistryApp from "./RegistryApp.svelte";
import { mount } from "svelte";
import { stripBase } from "./lib/router.js";

const pathname = stripBase(window.location.pathname).replace(/\/+$/, "");
const Root = pathname === "/registry" ? RegistryApp : App;
const app = mount(Root, { target: document.getElementById("app") });

export default app;
