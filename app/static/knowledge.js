const kb = id => document.getElementById(id);
const today = new Date();
const expiry = new Date(today); expiry.setFullYear(expiry.getFullYear() + 1);
kb("kb-effective").value = today.toISOString().slice(0, 10);
kb("kb-expires").value = expiry.toISOString().slice(0, 10);
const list = id => kb(id).value.split(",").map(value => value.trim()).filter(Boolean);
const headers = {"Content-Type":"application/json","X-BitAgent-Role":"admin"};
const knowledgeLanguage = () => window.bitAgentI18n?.language || "en";
let selectedFile = null;

function metadata() {
  const status = kb("kb-status").value;
  return {tenant_id:kb("kb-tenant").value.trim(),document_id:kb("kb-document-id").value.trim(),title:kb("kb-title").value.trim(),document_type:kb("kb-type").value,version:kb("kb-version").value.trim(),owner:kb("kb-owner").value.trim(),approval_status:status,approved_by_role:status === "approved" ? kb("kb-approver").value.trim() : null,effective_at:`${kb("kb-effective").value}T00:00:00Z`,expires_at:`${kb("kb-expires").value}T23:59:59Z`,data_class:kb("kb-class").value,allowed_roles:list("kb-roles"),keywords:list("kb-keywords"),source_ref:kb("kb-source").value.trim()};
}
function asBase64(file) { return new Promise((resolve,reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.onerror = reject; reader.readAsDataURL(file); }); }
kb("kb-file").addEventListener("change", event => { selectedFile = event.target.files[0] || null; if (!selectedFile) return; if (!kb("kb-title").value) kb("kb-title").value = selectedFile.name.replace(/\.[^.]+$/, ""); if (!kb("kb-document-id").value) kb("kb-document-id").value = selectedFile.name.toLowerCase().replace(/\.[^.]+$/, "").replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,""); kb("kb-file-state").textContent = `${selectedFile.name} · ${selectedFile.size} bytes · server extraction`; });

async function loadInventory() {
  const tenant = encodeURIComponent(kb("kb-tenant").value.trim());
  const response = await fetch(`/api/v0/xima/knowledge/documents?tenant_id=${tenant}`, {headers:{"X-BitAgent-Role":"admin"}});
  const payload = await response.json();
  if (!response.ok) throw new Error(JSON.stringify(payload.detail || payload));
  kb("inventory-count").textContent = `${payload.count} version(s)`;
  kb("inventory-list").replaceChildren(...payload.items.map(item => {
    const row = document.createElement("article"); row.className = "knowledge-item";
    const text = document.createElement("div"); const title = document.createElement("strong"); title.textContent = `${item.title} · v${item.version}`;
    const details = document.createElement("small"); details.textContent = `${item.document_id} · ${item.status} · ${item.lifecycle} · expires ${item.expires_at.slice(0,10)} · ${item.chunks.length} chunk(s)`;
    text.append(title,details); const button = document.createElement("button"); button.type="button"; button.textContent="Supersede"; button.disabled=item.status === "superseded";
    button.addEventListener("click", () => changeStatus(item,"superseded")); row.append(text,button); return row;
  }));
}
async function changeStatus(item,status) { const response = await fetch(`/api/v0/xima/knowledge/documents/${encodeURIComponent(item.document_id)}/versions/${encodeURIComponent(item.version)}/status`,{method:"POST",headers,body:JSON.stringify({tenant_id:item.tenant_id,status,changed_by_role:"admin",reason:"Superseded from knowledge management workspace"})}); if (!response.ok) throw new Error("Status transition failed"); await loadInventory(); }

async function importBitimenSource(source,buttonId) {
  const button=kb(buttonId); button.disabled=true; kb("bitimen-import-result").textContent="Fetching and processing…";
  try { const response=await fetch(`/api/v0/xima/knowledge/sources/${source}/import`,{method:"POST",headers,body:JSON.stringify({tenant_id:kb("kb-tenant").value.trim(),version:kb("kb-version").value.trim(),approval_status:"approved",allowed_roles:list("kb-roles")})}); const payload=await response.json(); if(!response.ok)throw new Error(JSON.stringify(payload.detail||payload)); kb("bitimen-import-result").textContent=JSON.stringify(payload,null,2); await loadInventory(); }
  catch(error){kb("bitimen-import-result").textContent=error.message;} finally{button.disabled=false;}
}
kb("bitimen-import").addEventListener("click",()=>importBitimenSource("bitimen-terms","bitimen-import"));
kb("bitimen-support-import").addEventListener("click",()=>importBitimenSource("bitimen-how-to-use","bitimen-support-import"));

kb("knowledge-form").addEventListener("submit", async event => { event.preventDefault(); kb("kb-process").disabled=true; kb("knowledge-state").textContent="processing"; try { let url="/api/v0/xima/knowledge/documents"; let body={...metadata(),content:kb("kb-content").value}; if(selectedFile){url+="/upload";body={document:metadata(),filename:selectedFile.name,content_base64:await asBase64(selectedFile)};} const response=await fetch(url,{method:"POST",headers,body:JSON.stringify(body)}); const payload=await response.json(); if(!response.ok)throw new Error(JSON.stringify(payload.detail||payload)); kb("kb-result").textContent=JSON.stringify(payload,null,2); kb("knowledge-state").textContent="processed"; kb("knowledge-state").className="pill good"; await loadInventory(); kb("qa-question").focus(); } catch(error){kb("kb-result").textContent=error.message;kb("knowledge-state").textContent="failed";kb("knowledge-state").className="pill warn";} finally{kb("kb-process").disabled=false;} });
kb("inventory-refresh").addEventListener("click",()=>loadInventory().catch(error=>{kb("inventory-list").textContent=error.message;}));
kb("qa-form").addEventListener("submit",async event=>{event.preventDefault();kb("qa-state").textContent="testing";try{const response=await fetch("/api/v0/xima/knowledge/qa",{method:"POST",headers:{"Content-Type":"application/json","X-BitAgent-Role":"operator"},body:JSON.stringify({tenant_id:kb("kb-tenant").value.trim(),question:kb("qa-question").value.trim(),language:knowledgeLanguage()})});const payload=await response.json();if(!response.ok)throw new Error(JSON.stringify(payload.detail||payload));const result=payload.result;kb("qa-answer").textContent=result.answer||result.limitations.join(" ");kb("qa-state").textContent=`${result.status} · ${result.citations.length} citation(s)`;kb("qa-state").className=result.answer?"pill good":"pill warn";}catch(error){kb("qa-answer").textContent=error.message;kb("qa-state").textContent="failed";kb("qa-state").className="pill warn";}});
kb("evaluation-form").addEventListener("submit",async event=>{event.preventDefault();const response=await fetch("/api/v0/xima/knowledge/evaluations",{method:"POST",headers,body:JSON.stringify({tenant_id:kb("kb-tenant").value.trim(),language:knowledgeLanguage(),cases:[{question:kb("evaluation-question").value.trim(),expected_document_ids:list("evaluation-expected")} ]})});const payload=await response.json();kb("evaluation-result").textContent=JSON.stringify(response.ok?payload.evaluation:payload.detail,null,2);});
loadInventory().catch(error=>{kb("inventory-list").textContent=error.message;});
