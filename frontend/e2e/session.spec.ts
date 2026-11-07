// Live API only: the login screen must bootstrap an anonymous session before authentication.
import { test, expect } from "./guard";

test("real: a fresh browser gets exactly one anonymous session before sign-in", async ({ page, context }) => {
  const issued: string[] = [];
  const requests: string[] = [];
  const responses: Array<Promise<void>> = [];
  page.on("request", request => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/")) requests.push(path);
  });
  page.on("response", response => {
    responses.push((async () => {
      const cookie = (await response.allHeaders())["set-cookie"];
      if (cookie?.includes("dd_session=")) issued.push(new URL(response.url()).pathname);
    })());
  });
  await page.goto("/#/scripts/new");
  await expect(page.getByRole("heading", { name: "Вход в систему" })).toBeVisible();
  await Promise.all(responses);
  expect(issued).toEqual(["/api/session"]);
  expect(requests).toEqual(["/api/session"]); // private workspace stays behind sign-in
  const session = (await context.cookies()).find(cookie => cookie.name === "dd_session");
  expect(session).toBeDefined();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Вход в систему" })).toBeVisible();
  await Promise.all(responses);
  expect(issued).toEqual(["/api/session"]);
  expect((await context.cookies()).find(cookie => cookie.name === "dd_session")?.value).toBe(session!.value);
});
