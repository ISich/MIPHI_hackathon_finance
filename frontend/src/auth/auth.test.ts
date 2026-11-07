import { mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { holder, resetMock, testApi } from "../test/mockApi";
import { waitFor } from "../test/dom";

vi.mock("../api/instance", async () => {
  const m = await import("../test/mockApi");
  return { api: m.testApi, IS_MOCK: false };
});
const { default: App } = await import("../App.vue");
const { default: LoginView } = await import("./LoginView.vue");
let wrapper: VueWrapper | undefined;

beforeEach(() => { resetMock(); });
afterEach(() => { wrapper?.unmount(); wrapper = undefined; });

it("does not fetch workspace data until the account signs in", async () => {
  window.location.hash = "#/scripts";
  wrapper = mount(App);
  await waitFor(() => expect(wrapper!.find(".login-form").exists()).toBe(true));
  expect(holder.calls.map(c => c.url)).toEqual(["/api/session"]);
  await wrapper.get("input[name=username]").setValue("admin");
  await wrapper.get("input[name=password]").setValue("admin12345");
  await wrapper.get("form").trigger("submit");
  await waitFor(() => expect(wrapper!.find(".session-profile").exists()).toBe(true));
  expect(window.location.hash).toBe("#/scripts");
  expect(holder.calls.some(c => c.url === "/api/scripts")).toBe(true);
});

it("prevents duplicate submits and allows retry after a network failure", async () => {
  let rejectLogin!: (reason: Error) => void;
  holder.fetch = () => new Promise((_resolve, reject) => { rejectLogin = reject; });
  wrapper = mount(LoginView);
  await wrapper.get("input[name=username]").setValue("admin");
  await wrapper.get("input[name=password]").setValue("admin12345");
  await wrapper.get("form").trigger("submit");
  await wrapper.get("form").trigger("submit");
  expect(holder.calls).toHaveLength(1);
  expect(wrapper.get("button[type=submit]").attributes("disabled")).toBeDefined();
  rejectLogin(new Error("offline"));
  await waitFor(() => expect(wrapper!.get('[role="alert"]').text()).toContain("Backend недоступен"));
  expect(wrapper.get("button[type=submit]").attributes("disabled")).toBeUndefined();
  resetMock();
  await wrapper.get("form").trigger("submit");
  await waitFor(() => expect(wrapper!.emitted("signedIn")).toHaveLength(1));
  expect((wrapper.get("input[name=password]").element as HTMLInputElement).value).toBe("");
});

it("retries session restoration without opening a private screen on failure", async () => {
  const inner = holder.fetch;
  holder.fetch = async () => { throw new Error("offline"); };
  wrapper = mount(App);
  await waitFor(() => expect(wrapper!.find('[role="alert"]').exists()).toBe(true));
  expect(wrapper.find(".dashboard-shell").exists()).toBe(false);
  holder.fetch = inner;
  await wrapper.get('[role="alert"] button').trigger("click");
  await waitFor(() => expect(wrapper!.find(".login-form").exists()).toBe(true));
  expect(wrapper.find('[role="alert"]').exists()).toBe(false);
});

it("checks the server session again when another tab signed out", async () => {
  await testApi.login("admin", "admin12345");
  wrapper = mount(App);
  await waitFor(() => expect(wrapper!.find(".session-profile").exists()).toBe(true));
  await testApi.logout();
  window.dispatchEvent(new Event("focus"));
  await waitFor(() => expect(wrapper!.find(".login-form").exists()).toBe(true));
  expect(wrapper.find(".dashboard-shell").exists()).toBe(false);
});
