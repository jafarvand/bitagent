const delivery = id => document.getElementById(id);
const adminHeaders = {"Content-Type":"application/json","X-BitAgent-Role":"admin"};
const tenant = () => delivery("delivery-tenant").value.trim();
const values = id => delivery(id).value.split(",").map(value => value.trim()).filter(Boolean);
const firstRun = new Date(Date.now() + 60000); firstRun.setSeconds(0, 0);
delivery("report-next").value = new Date(firstRun.getTime() - firstRun.getTimezoneOffset() * 60000).toISOString().slice(0,16);

async function jsonRequest(url, options={}) { const response=await fetch(url,options); const payload=await response.json(); if(!response.ok) throw new Error(JSON.stringify(payload.detail||payload)); return payload; }
async function loadDelivery() {
  delivery("delivery-refresh").disabled=true; delivery("delivery-message").textContent="Refreshing";
  try {
    const encoded=encodeURIComponent(tenant());
    const [posture,outbox]=await Promise.all([
      jsonRequest(`/api/v0/delivery/posture?tenant_id=${encoded}`,{headers:{"X-BitAgent-Role":"auditor"}}),
      jsonRequest(`/api/v0/delivery/outbox?tenant_id=${encoded}`,{headers:{"X-BitAgent-Role":"auditor"}}),
    ]);
    delivery("delivery-state").textContent=posture.ready?"Ready":"Blocked";
    delivery("delivery-auth").textContent=posture.webhook_authentication;
    delivery("delivery-subscription-count").textContent=posture.counts.subscriptions;
    delivery("delivery-queue-count").textContent=posture.counts.queued_notifications;
    delivery("outbox-count").textContent=`${outbox.items.length} item(s)`;
    delivery("outbox-list").replaceChildren(...outbox.items.map(item=>{
      const row=document.createElement("article"); row.className="knowledge-item";
      const text=document.createElement("div"); const title=document.createElement("strong"); title.textContent=`${item.severity} · ${item.channel} · ${item.status}`;
      const detail=document.createElement("small"); detail.textContent=`${item.event_id} · ${item.destination_ref} · ${item.notification_id}`; text.append(title,detail); row.append(text);
      if(item.status!=="acknowledged"){const button=document.createElement("button");button.type="button";button.textContent="Acknowledge";button.addEventListener("click",async()=>{await jsonRequest(`/api/v0/delivery/outbox/${encodeURIComponent(item.notification_id)}/acknowledge?tenant_id=${encoded}&actor=delivery-console`,{method:"POST",headers:adminHeaders});await loadDelivery();});row.append(button);} return row;
    }));
    if(!outbox.items.length) delivery("outbox-list").textContent="No tenant notifications are queued.";
    delivery("delivery-message").textContent="Updated";
  } catch(error) { delivery("delivery-message").textContent=error.message; delivery("delivery-message").className="error"; }
  finally { delivery("delivery-refresh").disabled=false; }
}
delivery("delivery-refresh").addEventListener("click",loadDelivery);
delivery("subscription-form").addEventListener("submit",async event=>{event.preventDefault();try{const payload=await jsonRequest("/api/v0/delivery/subscriptions",{method:"POST",headers:adminHeaders,body:JSON.stringify({tenant_id:tenant(),domain:delivery("delivery-domain").value,event_type:delivery("delivery-event-type").value.trim(),minimum_severity:delivery("delivery-severity").value,channel:delivery("delivery-channel").value,destination_ref:delivery("delivery-destination").value.trim(),owner:delivery("delivery-owner").value.trim()})});delivery("subscription-result").textContent=JSON.stringify(payload.subscription,null,2);await loadDelivery();}catch(error){delivery("subscription-result").textContent=error.message;}});
delivery("schedule-form").addEventListener("submit",async event=>{event.preventDefault();try{const payload=await jsonRequest("/api/v0/delivery/report-schedules",{method:"POST",headers:adminHeaders,body:JSON.stringify({tenant_id:tenant(),report_type:delivery("report-type").value,interval_minutes:Number(delivery("report-interval").value),next_run_at:new Date(delivery("report-next").value).toISOString(),recipient_refs:values("report-recipients"),owner:delivery("report-owner").value.trim()})});delivery("schedule-result").textContent=JSON.stringify(payload.schedule,null,2);await loadDelivery();}catch(error){delivery("schedule-result").textContent=error.message;}});
loadDelivery();
