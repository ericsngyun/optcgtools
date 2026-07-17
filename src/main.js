import App from "./App.svelte";
import "../public/css/cards.css";
import "../public/css/cards/base.css";
import "../public/css/cards/one-piece-sp.css";
import "../public/css/cards/one-piece-alt-art.css";
import "./site.css";
import "./research.css";

const app = new App({
  target: document.getElementById("app")
});

export default app;
