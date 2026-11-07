import { createApp } from "vue";
import App from "./App.vue";
import { deepLinkToHash } from "./router";
import "./fonts.css";
import "./styles.css";

const deep = deepLinkToHash(window.location.pathname, window.location.search);
if (deep) window.history.replaceState(null, "", "/" + deep);

createApp(App).mount("#root");
