// Exercise the browser against the running Compose service using a disposable account.
const { chromium } = require("playwright");
const { execFileSync } = require("node:child_process");
async function run() {
  const fixture = JSON.parse(execFileSync("docker", ["compose", "exec", "-T", "api", "python", "-c",
    "from aegis.demo import sample_pdf; import json,base64,os; print(json.dumps([json.loads(os.environ['AEGIS_KEYS'])['local'],base64.b64encode(sample_pdf()).decode()]))"]));
  const browser = await chromium.launch({channel:"chrome"});
  try {
    const page = await browser.newPage();
    await page.goto("http://127.0.0.1:8000/");
    await page.locator("#key").fill(fixture[0]);
    await page.getByText("Unlock workspace").click();
    await page.locator("#pdf").setInputFiles({name:"workspace-test.pdf",mimeType:"application/pdf",buffer:Buffer.from(fixture[1],"base64")});
    await page.getByRole("button",{name:"Upload PDF"}).click();
    await page.getByText("PDF ready.").waitFor();
    await page.locator("#question").fill("archive retention");
    await page.getByText("Find evidence").click();
    await page.locator("#result strong").filter({hasText:"Page 2"}).first().waitFor();
    await page.locator("blockquote").filter({hasText:"45 days"}).first().waitFor();
    await page.getByText("Lock workspace").click();
    await page.getByText("Unlock workspace").waitFor();
  } finally { await browser.close(); }
}
run().catch(error => { console.error(error.message); process.exitCode=1; });
