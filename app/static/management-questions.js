const questions = [
[1,'executive','Give me a concise executive summary of the exchange’s current status.','supported',['daily-executive-brief','exchange-health'],[]],
[2,'executive','What are the three most important risks requiring management attention today?','supported',['cross-domain-prioritization','incident-priority'],[]],
[3,'business','How did revenue, trading volume, active users, and fees change compared with yesterday and last week?','supported',['business-performance','period-comparison'],[]],
[4,'business','Which products, markets, or customer segments generated the most revenue and growth?','partial',['segment-performance','product-growth'],['customer-segment profitability view','product revenue attribution']],
[5,'operations','Which services currently have abnormal latency, errors, or resource usage?','supported',['service-health','capacity-report'],[]],
[6,'operations','Why are deposits or withdrawals for a specific asset delayed?','partial',['transaction-delay-investigation','withdrawal-slowdown'],['queues API','workers API','networks API']],
[7,'operations','What incidents occurred during the last 24 hours, and what caused them?','partial',['incident-summary','root-cause-hypothesis'],['dependency API','queues API','workers API','networks API']],
[8,'operations','Which infrastructure problems are most likely to affect customers in the next few hours?','partial',['predictive-infrastructure-risk','capacity-forecast'],['historical infrastructure metrics']],
[9,'market-risk','What is our current net exposure for each asset, and which exposures exceed approved limits?','supported',['asset-exposure','risk-limit-breach'],[]],
[10,'market-risk','How did the market maker perform during the last 24 hours in terms of profit, spread, volume, and inventory risk?','partial',['market-maker-performance','inventory-risk'],['order-book depth','market-maker PnL attribution']],
[11,'market-risk','Which markets currently have insufficient liquidity, excessive spread, or abnormal slippage?','partial',['market-quality','liquidity-risk'],['order-book depth API']],
[12,'market-risk','What would happen to our exposure and liquidity if BTC or another major asset moved by 10%?','partial',['market-stress-testing','scenario-analysis'],['deterministic scenario service']],
[13,'treasury','Are hot-wallet balances sufficient for expected withdrawals during the next six hours?','partial',['wallet-sufficiency','withdrawal-demand-forecast'],['network status','forecast inputs']],
[14,'treasury','Which assets require wallet rebalancing, and how much should be transferred?','partial',['wallet-rebalancing-proposal','treasury-approval'],['network status','approved wallet thresholds']],
[15,'treasury','Are there discrepancies between blockchain balances, wallet records, and the internal ledger?','supported',['treasury-reconciliation','financial-integrity-alert'],[]],
[16,'treasury','Which pending blockchain transactions are stuck, delayed, underfunded, or at risk of failure?','partial',['pending-transaction-monitoring','fee-analysis'],['networks API','fee and nonce telemetry']],
[17,'aml-fraud','Which users or transactions currently have the highest AML or fraud risk, and why?','supported',['aml-priority','user-risk-timeline'],[]],
[18,'aml-fraud','Are there signs of account takeover, coordinated abuse, wash trading, spoofing, or withdrawal fraud?','partial',['account-takeover','market-manipulation'],['relationship graph','full order-event telemetry']],
[19,'security','What are the most serious security alerts, suspicious logins, API-key activities, or administrative changes today?','supported',['security-daily-brief','authentication-anomaly'],[]],
[20,'marketing','Which customer segments are growing or declining, why are users becoming inactive, and what campaigns or retention actions should we prioritize?','partial',['growth-segmentation','churn-retention','campaign-planning'],['customer cohort analytics','live churn features','campaign attribution']]
].map(([id,domain,question,coverage,useCases,missing])=>({id,domain,question,coverage,useCases,missing}));

const domain = document.querySelector('#domain');
const coverage = document.querySelector('#coverage');
const search = document.querySelector('#search');
const reset = document.querySelector('#reset');
const grid = document.querySelector('#questions');
const summary = document.querySelector('#summary');

[...new Set(questions.map(q=>q.domain))].sort().forEach(value=>domain.insertAdjacentHTML('beforeend',`<option value="${value}">${value}</option>`));

function renderSummary(rows){
  const count = state => rows.filter(q=>q.coverage===state).length;
  const weighted = rows.length ? Math.round(((count('supported') + count('partial')*.5) / rows.length)*100) : 0;
  summary.innerHTML = `<div class="mq-stat"><strong>${rows.length}</strong><span>visible questions</span></div><div class="mq-stat"><strong>${count('supported')}</strong><span>supported</span></div><div class="mq-stat"><strong>${count('partial')}</strong><span>partial</span></div><div class="mq-stat"><strong>${weighted}%</strong><span>weighted readiness</span></div>`;
}

function render(){
  const needle = search.value.trim().toLowerCase();
  const rows = questions.filter(q => (!domain.value || q.domain===domain.value) && (!coverage.value || q.coverage===coverage.value) && (!needle || `${q.question} ${q.useCases.join(' ')} ${q.missing.join(' ')}`.toLowerCase().includes(needle)));
  renderSummary(rows);
  grid.innerHTML = rows.length ? rows.map(q=>`<article class="mq-card"><div class="mq-head"><h2>${q.id}. ${q.question}</h2><span class="pill ${q.coverage}">${q.coverage}</span></div><div class="mq-meta"><strong>Domain:</strong> ${q.domain}<br><strong>Use cases:</strong> ${q.useCases.join(', ')}</div>${q.missing.length?`<div class="mq-missing"><strong>Missing evidence:</strong> ${q.missing.join(', ')}</div>`:''}</article>`).join('') : '<div class="mq-empty">No questions match the selected filters.</div>';
}

[domain,coverage,search].forEach(el=>el.addEventListener(el===search?'input':'change',render));
reset.addEventListener('click',()=>{domain.value='';coverage.value='';search.value='';render();});
render();
