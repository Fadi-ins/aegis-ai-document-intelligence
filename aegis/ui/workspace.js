"use strict";
const el = id => document.getElementById(id);
let key = "";
let generation = 0;
function node(tag, text) {
  const item = document.createElement(tag);
  item.textContent = text;
  return item;
}
async function api(path, options = {}) {
  const response = await fetch("/api/v1/" + path, {
    ...options, redirect: "error", cache: "no-store",
    headers: {...options.headers, Authorization: "Bearer " + key}
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Request failed");
  return data;
}
function form(id, action) {
  el(id).onsubmit = async event => {
    event.preventDefault();
    const version = generation;
    const button = event.currentTarget.querySelector("button");
    button.disabled = true;
    el("status").textContent = "Working…";
    try {
      const done = await action();
      if (version === generation) done();
    } catch (err) {
      if (version === generation) el("status").textContent = err.message;
    } finally { button.disabled = false; }
  };
}
function sources(docs, selected = []) {
  el("sources").replaceChildren();
  if (!docs.length) el("sources").append(node("p", "Upload a PDF to start."));
  for (const doc of docs) {
    const label = node("label", "");
    const box = document.createElement("input");
    box.type = "checkbox"; box.value = doc.id; box.checked = selected.includes(doc.id);
    label.append(box, " " + doc.filename + " · " + doc.pages + " pp.");
    el("sources").append(label);
  }
}
const selected = () => Array.from(el("sources").querySelectorAll(":checked"), box => box.value);
form("connect", async () => {
  key = el("key").value.trim();
  const docs = await api("documents");
  return () => {
    el("key").value = ""; el("connect").hidden = true; el("workspace").hidden = false;
    sources(docs, docs.length === 1 ? [docs[0].id] : []); el("status").textContent = "";
  };
});
el("lock").onclick = () => {
  generation++; key = ""; el("workspace").hidden = true; el("connect").hidden = false;
  for (const id of ["sources","result","status"]) el(id).replaceChildren();
  el("ask").reset(); el("upload").reset(); el("key").focus();
};
form("upload", async () => {
  const file = el("pdf").files[0];
  if (file.size > 4194304) throw new Error("Choose a PDF under 4 MiB.");
  const data = new FormData(); data.append("file", file);
  const session = generation;
  const doc = await api("documents", {method:"POST", body:data});
  if (generation !== session) return () => {};
  const docs = await api("documents");
  return () => { sources(docs, [...selected(), doc.id]); el("upload").reset(); el("status").textContent = "PDF ready."; };
});
form("ask", async () => {
  el("result").replaceChildren();
  const ids = selected();
  if (!ids.length || ids.length > 8) throw new Error("Select between one and eight sources.");
  const data = await api("chat/query", {method:"POST", headers:{"Content-Type":"application/json"},
    body:JSON.stringify({question:el("question").value, document_ids:ids})});
  return () => {
    const result = el("result");
    result.append(node("h3", {matching_passages:"Matching passages",quoted_answer:"Cited answer",insufficient_evidence:"Insufficient evidence"}[data.status]));
    if (data.answer) result.append(node("p", data.answer));
    for (const c of data.citations) result.append(node("strong", c.filename + " · Page " + c.page),node("blockquote", c.quote));
    el("status").textContent = "";
  };
});
