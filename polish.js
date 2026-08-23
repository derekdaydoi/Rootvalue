// Rootvalue product layer — brand, knowledge, data accuracy and resilient dashboard fallback.
(() => {
  Object.assign(I18N.vi,{
    'brand.tag':'Nghiên cứu đầu tư dựa trên dữ kiện.','nav.overview':'Bản tin sáng','nav.overview.short':'Bản tin','nav.knowledge':'Kiến thức','nav.knowledge.short':'Kiến thức',
    'missing.interbank_rate':'Lãi suất liên ngân hàng','missing.policy_rate':'Lãi suất điều hành','missing.omo':'Nghiệp vụ thị trường mở','missing.credit':'Tăng trưởng tín dụng','missing.money_supply':'Cung tiền M2','missing.cpi':'CPI','missing.exchange_rate':'Tỷ giá NHNN'
  });
  Object.assign(I18N.en,{
    'brand.tag':'Evidence-led investment research.','nav.overview':'Morning brief','nav.overview.short':'Brief','nav.knowledge':'Knowledge','nav.knowledge.short':'Knowledge',
    'missing.interbank_rate':'Interbank rates','missing.policy_rate':'Policy rates','missing.omo':'Open-market operations','missing.credit':'Credit growth','missing.money_supply':'M2 money supply','missing.cpi':'CPI','missing.exchange_rate':'SBV exchange rate'
  });

  const rvOriginalSourceLabel=sourceLabel;
  sourceLabel=function(source){
    const raw=Array.isArray(source)?source.join(' · '):String(source||'');
    if(/State Bank of Vietnam/i.test(raw))return STATE.lang==='vi'?'Ngân hàng Nhà nước Việt Nam':'State Bank of Vietnam';
    if(/KBS\/VCI via Vnstock community/i.test(raw))return STATE.lang==='vi'?'KBS/VCI qua Vnstock':'KBS/VCI via Vnstock';
    if(/KBS via Vnstock community/i.test(raw))return STATE.lang==='vi'?'KBS qua Vnstock':'KBS via Vnstock';
    return rvOriginalSourceLabel(source);
  };

  const rvLocalizedCompanyRender=renderCompany;
  renderCompany=function(){
    const screen=$('[data-screen="company"]');
    if(screen&&screen.dataset.analysisLang!==STATE.lang){screen.dataset.analysisShell='0';screen.dataset.analysisLang=STATE.lang;}
    rvLocalizedCompanyRender();
    if(screen)screen.dataset.analysisLang=STATE.lang;
  };

  const txt=(vi,en)=>STATE.lang==='vi'?vi:en;
  const esc=(v)=>String(v??'').replace(/[&<>'"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[m]));
  const rich=(v)=>esc(v).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
  const brandMarkup=()=>`<div class="rv-brand"><img class="rv-logo-mark" src="assets/rootvalue-mark.svg" alt="Rootvalue"><div class="rv-brand-copy"><div class="rv-brand-word"><span class="root">ROOT</span><span class="value">VALUE</span></div><div class="rv-brand-tag">From zero to wealth.</div></div></div>`;

  function initBrand(){
    const lock=$('.brand-lockup');if(lock)lock.innerHTML=brandMarkup();
    const mobile=$('.mobile-head .brand-word');if(mobile)mobile.outerHTML=brandMarkup();
    const side=$('.sidebar');if(side){let copyright=$('.rv-copyright',side);if(!copyright){copyright=document.createElement('div');copyright.className='rv-copyright';side.appendChild(copyright);}copyright.innerHTML=`© 2026 <strong>derekdaydoi</strong><br>${txt('Rootvalue · Dữ liệu trước nhận định.','Rootvalue · Evidence before opinion.')}`;}
    const main=$('.main');if(main){let footer=$('.rv-page-footer',main);if(!footer){footer=document.createElement('footer');footer.className='rv-page-footer';main.appendChild(footer);}footer.innerHTML=`<span>Rootvalue · From zero to wealth.</span><span>${txt('Dữ liệu trước nhận định.','Evidence before opinion.')} · © 2026 derekdaydoi</span>`;}
  }

  let KNOWLEDGE=null;let KNOWLEDGE_TAB='library';let KNOWLEDGE_FOCUS=null;let GLOBAL=null;
  function ensureKnowledgeRoute(){
    $$('[data-route="knowledge"]').forEach(btn=>{if(btn.dataset.knowledgeBound)return;btn.dataset.knowledgeBound='1';btn.addEventListener('click',()=>renderKnowledge());});
  }
  function openKnowledge(){
    navigate('knowledge');renderKnowledge();
  }
  function renderBlock(b){
    if(!b)return'';if(b.type==='heading'){const n=Math.min(3,Math.max(2,Number(b.level)||2));return `<h${n}>${rich(b.text)}</h${n}>`;}
    if(b.type==='paragraph')return `<p>${rich(b.text)}</p>`;
    if(b.type==='formula')return `<div class="formula">${rich(b.text)}</div>`;
    if(b.type==='quote')return `<blockquote>${rich(b.text)}</blockquote>`;
    if(b.type==='image')return `<img src="${esc(b.src)}" alt="${esc(b.alt||'')}">`;
    if(b.type==='bullets')return `<ul>${(b.items||[]).map(x=>`<li>${rich(x)}</li>`).join('')}</ul>`;return'';
  }
  function renderArticle(item,isBlog=false){
    const root=$('#rvKnowledgeRoot');if(!root||!item)return;const title=STATE.lang==='vi'?item.title_vi:item.title_en;const blocks=STATE.lang==='vi'?(item.blocks_vi||[]):(item.blocks_en||[]);
    KNOWLEDGE_FOCUS={kind:isBlog?'blog':'topic',id:item.id};root.innerHTML=`<button type="button" class="rv-back-btn" id="rvKnowledgeBack">← ${txt('Quay lại','Back')}</button><article class="rv-article"><div class="eyebrow">${esc(isBlog?txt('BÀI VIẾT','ARTICLE'):(STATE.lang==='vi'?item.category_vi:item.category_en))}</div><h1>${esc(title)}</h1>${isBlog&&item.image?`<img src="${esc(item.image)}" alt="${esc(title)}">`:''}${blocks.map(renderBlock).join('')}</article>`;
    $('#rvKnowledgeBack').onclick=()=>{renderKnowledge();requestAnimationFrame(()=>{const target=$$('[data-topic],[data-blog]').find(el=>(el.dataset.topic||el.dataset.blog)===KNOWLEDGE_FOCUS?.id);target?.focus();});};
  }
  function bindCardActivation(elements,handler){elements.forEach(el=>{const activate=()=>handler(el);el.onclick=activate;el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();activate();}};});}
  function renderKnowledge(){
    const root=$('#rvKnowledgeRoot');if(!root)return;if(!KNOWLEDGE){root.innerHTML=`<div class="notice">${txt('Đang tải thư viện kiến thức…','Loading knowledge library…')}</div>`;return;}
    const topics=KNOWLEDGE.topics||[],blogs=KNOWLEDGE.blogs||[];
    root.innerHTML=`<div class="rv-knowledge-hero"><div class="rv-knowledge-hero-copy"><div class="eyebrow">${txt('ROOTVALUE KNOWLEDGE','ROOTVALUE KNOWLEDGE')}</div><h1>${txt('Kiến thức','Knowledge')}</h1><p>${txt('Thư viện nền tảng về dòng tiền Việt Nam, công cụ NHNN, bảng cân đối và kinh tế vĩ mô. Mục tiêu là lưu framework và dữ kiện để dùng lại khi phân tích, không biến kiến thức thành tín hiệu mua bán.','A working library for Vietnam money flows, SBV tools, balance sheets and macro. It stores reusable frameworks and evidence, not buy/sell signals.')}</p></div><img src="assets/vietnam-money-flow.svg" alt="Vietnam money-flow map"></div><div class="rv-knowledge-tabs" role="tablist"><button type="button" role="tab" aria-selected="${KNOWLEDGE_TAB==='library'}" class="rv-knowledge-tab ${KNOWLEDGE_TAB==='library'?'active':''}" data-ktab="library">${txt('Thư viện','Library')}</button><button type="button" role="tab" aria-selected="${KNOWLEDGE_TAB==='blog'}" class="rv-knowledge-tab ${KNOWLEDGE_TAB==='blog'?'active':''}" data-ktab="blog">${txt('Bài viết','Articles')}</button></div><div id="rvKnowledgeBody"></div>`;
    $$('[data-ktab]',root).forEach(b=>b.onclick=()=>{KNOWLEDGE_TAB=b.dataset.ktab;renderKnowledge()});
    const body=$('#rvKnowledgeBody');
    if(KNOWLEDGE_TAB==='blog')body.innerHTML=`<div class="rv-blog-list">${blogs.map(x=>{const title=STATE.lang==='vi'?x.title_vi:x.title_en;return `<article class="blog-card" role="button" tabindex="0" aria-label="${esc(title)}" data-blog="${esc(x.id)}"><img src="${esc(x.image||'assets/vietnam-money-flow.svg')}" alt=""><div class="body"><div class="eyebrow">${esc(x.date||'')}</div><h3>${esc(title)}</h3><p>${esc(STATE.lang==='vi'?x.excerpt_vi:x.excerpt_en)}</p></div></article>`}).join('')}</div>`;
    else body.innerHTML=`<div class="rv-knowledge-grid">${topics.map((x,i)=>{const title=STATE.lang==='vi'?x.title_vi:x.title_en;return `<article class="knowledge-card ${i===0?'wide':''}" role="button" tabindex="0" aria-label="${esc(title)}" data-topic="${esc(x.id)}"><div class="eyebrow">${esc(STATE.lang==='vi'?x.category_vi:x.category_en)}</div><h2>${esc(title)}</h2><p>${esc(STATE.lang==='vi'?x.summary_vi:x.summary_en)}</p></article>`}).join('')}</div>`;
    bindCardActivation($$('[data-topic]',body),el=>renderArticle(topics.find(x=>x.id===el.dataset.topic),false));bindCardActivation($$('[data-blog]',body),el=>renderArticle(blogs.find(x=>x.id===el.dataset.blog),true));
  }

  function formatGlobal(key,node){const v=toFinite(node?.latest);if(v===null)return'N/A';if(key==='fed_total_assets')return `$${(v/1e6).toFixed(2)}T`;if(key==='fed_overnight_rrp')return `$${v.toFixed(1)}B`;if(['fed_funds_effective','us_2y','us_10y'].includes(key))return `${v.toFixed(2)}%`;if(key==='wti')return `$${v.toFixed(1)}`;return v.toFixed(2)}
  function globalSeriesState(node){if(node?.status==='stale'||node?.freshness==='stale')return'stale';if(node?.status==='ok'&&toFinite(node?.latest)!==null)return'current';return toFinite(node?.latest)!==null?'partial':'missing'}
  function globalSeriesFresh(node){return globalSeriesState(node)==='current'}
  function globalSeriesStateLabel(state){return state==='current'?txt('MỚI','CURRENT'):state==='stale'?txt('QUÁ HẠN','STALE'):state==='partial'?txt('MỘT PHẦN','PARTIAL'):txt('THIẾU','MISSING')}
  function globalSeriesAsOf(node){return `${txt('Ngày nguồn','As of')} ${dateText(node?.as_of)}`}
  const OFFICIAL_NEWS_DOMAINS=['federalreserve.gov','newyorkfed.org','stlouisfed.org','ecb.europa.eu','bis.org','imf.org','worldbank.org'];
  function officialNewsUrl(raw){try{const url=new URL(String(raw||''),window.location.href);if(url.protocol!=='https:')return null;const host=url.hostname.toLowerCase();return OFFICIAL_NEWS_DOMAINS.some(domain=>host===domain||host.endsWith(`.${domain}`))?url.href:null;}catch(_){return null;}}
  function ensureGlobalPanel(){
    const money=$('[data-screen="money"]');if(!money)return;let panel=$('#rvGlobalPanel');if(!panel){panel=document.createElement('article');panel.id='rvGlobalPanel';panel.className='rv-global-panel';const flow=$('.flow-map',money);money.insertBefore(panel,flow||money.firstChild);}renderGlobal();renderReactionInputs();
  }
  function renderGlobal(){
    const root=$('#rvGlobalPanel');if(!root)return;if(!GLOBAL){root.innerHTML=`<div class="rv-global-head"><div><div class="eyebrow">${txt('BÊN NGOÀI','EXTERNAL')}</div><h2>${txt('Fed & điều kiện tài chính toàn cầu','Fed & global financial conditions')}</h2></div><span class="rv-global-note">${txt('Đang chờ data/global.json','Waiting for data/global.json')}</span></div>`;return;}
    const s=GLOBAL.series||{};const keys=['fed_funds_effective','fed_total_assets','fed_overnight_rrp','broad_dollar','us_10y'];
    const cards=keys.map(k=>{const n=s[k]||{},seriesState=globalSeriesState(n);return `<div class="rv-global-metric ${seriesState}"><div class="rv-global-metric-head"><span>${esc(n.label||k)}</span><b class="rv-series-status ${seriesState}">${esc(globalSeriesStateLabel(seriesState))}</b></div><strong>${esc(formatGlobal(k,n))}</strong><small>${esc(globalSeriesAsOf(n))} · ${esc(n.frequency||'')} · ${esc(n.source||'')}</small></div>`}).join('');
    const news=(GLOBAL.news||[]).slice(0,6).map(n=>{const url=officialNewsUrl(n.url);const headline=url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>`:`<span class="headline">${esc(n.title)}</span>`;return `<div class="rv-news-item"><span class="src">${esc(n.source)}</span>${headline}<time>${esc(n.published||'')}</time></div>`}).join('');
    root.innerHTML=`<div class="rv-global-head"><div><div class="eyebrow">${txt('BÊN NGOÀI','EXTERNAL')}</div><h2>${txt('Fed & điều kiện tài chính toàn cầu','Fed & global financial conditions')}</h2></div><span class="rv-global-note">${esc(GLOBAL.freshness_class||'')}</span></div><div class="rv-global-grid">${cards}</div><div class="rv-news-list">${news||`<div class="muted">${txt('Chưa có headline từ nguồn chính thức.','No official-source headlines yet.')}</div>`}</div>`;
    const fed=s.fed_funds_effective,broad=s.broad_dollar,externalInputs=[fed,broad],externalFresh=externalInputs.every(globalSeriesFresh),externalStale=externalInputs.some(node=>globalSeriesState(node)==='stale'),external=$('#externalValue');if(external){const stateLabel=externalFresh?'':externalStale?txt('QUÁ HẠN','STALE'):txt('CHƯA SẴN SÀNG','NOT READY');external.classList.toggle('stale-data',!externalFresh);external.textContent=`${stateLabel?`${stateLabel} · `:''}Fed ${formatGlobal('fed_funds_effective',fed)} (${globalSeriesAsOf(fed)}) · USD ${formatGlobal('broad_dollar',broad)} (${globalSeriesAsOf(broad)})`;}
  }
  function renderReactionInputs(){
    const status=$('#reactionStatus'),missing=$('#missingCore');if(!status||!missing)return;let grid=$('#rvReactionGrid');if(!grid){grid=document.createElement('div');grid.id='rvReactionGrid';grid.className='rv-reaction-grid';missing.parentNode.insertBefore(grid,missing);}const metrics=STATE.data?.macro?.metrics||[];const has=(k)=>metrics.some(x=>x.key===k&&toFinite(x.value)!==null),globalSeries=GLOBAL?.series||{},externalInputs=[globalSeries.fed_funds_effective,globalSeries.broad_dollar],globalReady=externalInputs.every(globalSeriesFresh),globalStale=externalInputs.some(node=>globalSeriesState(node)==='stale'),globalDates=externalInputs.map(globalSeriesAsOf).join(' · ');const items=[
      [txt('Ngoại lực','External'),globalReady,globalReady?`${txt('Fed/USD mới','Fed/USD current')} · ${globalDates}`:globalStale?`${txt('quá hạn','stale')} · ${globalDates}`:txt('thiếu dữ liệu fresh','fresh inputs missing')],
      ['OMO',has('sbv_omo_awarded'),has('sbv_omo_awarded')?txt('có snapshot chính thức','official snapshot'):txt('thiếu','missing')],
      [txt('M2 / tiền gửi','M2 / deposits'),has('sbv_m2_growth'),has('sbv_m2_growth')?txt('có snapshot chính thức','official snapshot'):txt('thiếu','missing')],
      [txt('Liên ngân hàng','Interbank'),false,txt('thiếu chuỗi lịch sử','history missing')],
      [txt('Tỷ giá NHNN','SBV FX'),false,txt('thiếu chuỗi lịch sử','history missing')],
      [txt('Tín dụng + CPI','Credit + CPI'),false,txt('thiếu chuỗi lịch sử','history missing')]
    ];grid.innerHTML=items.map(x=>`<div class="rv-reaction-cell ${x[1]?'ok':'missing'}"><span>${esc(x[0])}</span><strong>${esc(x[2])}</strong></div>`).join('');const ready=items.filter(x=>x[1]).length;status.textContent=`${ready}/${items.length} ${txt('nhóm đầu vào có dữ liệu','input groups observed')}`;status.className=`pill ${ready===items.length?'ok':'warning'}`;
  }

  function injectAccuracy(){
    const screen=$('[data-screen="data"]');if(!screen)return;const head=$('.screen-head',screen);let box=$('#rvAccuracyPanel',screen);if(!box){box=document.createElement('article');box.id='rvAccuracyPanel';box.className='rv-accuracy-panel';if(head)head.insertAdjacentElement('afterend',box);else screen.prepend(box);}box.innerHTML=`<div class="rv-accuracy-head"><div><div class="eyebrow">${txt('NHỊP DỮ LIỆU','DATA CADENCE')}</div><h3>${txt('Ngày nguồn và thời điểm Rootvalue lấy dữ liệu được tách riêng','Source date and Rootvalue fetch time are kept separate')}</h3><p>${txt('Mỗi lớp chạy theo nhịp hợp lý của nguồn; lỗi refresh giữ bản tốt gần nhất và được đánh dấu stale thay vì xóa dữ liệu.','Each layer follows its source cadence; a refresh failure retains the last known good snapshot and marks it stale instead of erasing it.')}</p></div><span class="rv-freshness-badge">Source-aware</span></div><div class="rv-freshness-grid"><div class="rv-freshness-item"><b>${txt('Thị trường','Market')}</b><span>${txt('Ngày giao dịch · sau đóng cửa','Trading days · after close')}</span></div><div class="rv-freshness-item"><b>Fed / Global</b><span>${txt('Poll hàng giờ · chỉ ghi khi có thay đổi','Hourly poll · write on change')}</span></div><div class="rv-freshness-item"><b>NHNN</b><span>${txt('Hằng ngày · ngày quan sát nguồn','Daily · source observation date')}</span></div><div class="rv-freshness-item"><b>${txt('BCTC','Financials')}</b><span>${txt('Chủ nhật · bản chất quý/năm','Sunday · quarterly/annual source')}</span></div></div>`;
  }

  function payloadRows(report){const d=report?.data||{};const cols=d.columns||[];return (d.rows||[]).map(row=>Object.fromEntries(cols.map((c,i)=>[String(c),row[i]])))}
  function pickRow(rows,ids){for(const id of ids){const r=rows.find(x=>String(x.item_id||x.id||'').trim()===id);if(r)return r}return null}
  function series(row){if(!row)return[];return Object.entries(row).flatMap(([period,value])=>{const n=toFinite(value);return /^20\d{2}/.test(period)&&n!==null?[{period,value:n}]:[]}).sort((a,b)=>String(a.period).localeCompare(String(b.period)))}
  function combine(a,b,fn){const A=new Map(a.map(x=>[x.period,x.value])),B=new Map(b.map(x=>[x.period,x.value]));return [...new Set([...A.keys(),...B.keys()])].sort().flatMap(p=>{if(!A.has(p)||!B.has(p))return[];const value=toFinite(fn(A.get(p),B.get(p)));return value===null?[]:[{period:p,value}];});}
  function buildFreq(reports){
    const inc=payloadRows(reports?.income_statement),cf=payloadRows(reports?.cash_flow),bs=payloadRows(reports?.balance_sheet);const r={};
    r.revenue=series(pickRow(inc,['net_revenue','revenue']));r.cogs=series(pickRow(inc,['cost_of_goods_sold']));r.gross_profit=series(pickRow(inc,['gross_profit']));r.operating_profit=series(pickRow(inc,['operating_profit']));r.net_profit=series(pickRow(inc,['profit_after_tax_for_shareholders_of_parent_company','net_profit']));r.interest_expense=series(pickRow(inc,['of_which_interest_expense','interest_expense']));
    r.cfo=series(pickRow(cf,['operating_cash_flow','net_cash_flows_from_operating_activities','net_cash_flow_from_operating_activities']));r.capex=series(pickRow(cf,['payment_for_fixed_assets_constructions_and_other_long_term_assets','purchase_of_fixed_assets','purchase_of_fixed_assets_and_other_long_term_assets']));r.fcf=r.cfo.length&&r.capex.length?combine(r.cfo,r.capex,(x,y)=>x+y):[];
    r.total_assets=series(pickRow(bs,['total_assets','total_asset']));r.current_assets=series(pickRow(bs,['current_assets','total_current_assets']));r.current_liabilities=series(pickRow(bs,['current_liabilities','total_current_liabilities']));r.cash=series(pickRow(bs,['cash_and_cash_equivalents','cash']));r.receivables=series(pickRow(bs,['short_term_receivables','receivables']));r.inventory=series(pickRow(bs,['inventories','inventory']));r.ppe=series(pickRow(bs,['fixed_assets','tangible_fixed_assets','property_plant_equipment']));r.cip=series(pickRow(bs,['construction_in_progress','construction_in_progress_cost']));r.payables=series(pickRow(bs,['trade_payables','short_term_trade_payables']));r.short_debt=series(pickRow(bs,['short_term_borrowings','short_term_debt','short_term_borrowings_and_finance_lease_liabilities']));r.long_debt=series(pickRow(bs,['long_term_borrowings','long_term_debt','long_term_borrowings_and_finance_lease_liabilities']));
    r.total_debt=r.short_debt.length&&r.long_debt.length?combine(r.short_debt,r.long_debt,(x,y)=>x+y):[];r.nwc=combine(r.current_assets,r.current_liabilities,(x,y)=>x-y);r.operating_nwc=r.receivables.length&&r.inventory.length&&r.payables.length?combine(combine(r.receivables,r.inventory,(x,y)=>x+y),r.payables,(x,y)=>x-y):[];r.gross_margin=combine(r.gross_profit,r.revenue,(x,y)=>y?x/y:null);r.net_margin=combine(r.net_profit,r.revenue,(x,y)=>y?x/y:null);r.cfo_to_profit=combine(r.cfo,r.net_profit,(x,y)=>y?x/y:null);
    return {series:r,asset_mix:{cash:r.cash,receivables:r.receivables,inventory:r.inventory,ppe:r.ppe,cip:r.cip,other:[]},report_availability:{balance_sheet:!!bs.length,income_statement:!!inc.length,cash_flow:!!cf.length}};
  }
  window.rvBuildDashboardFallback=function(rows={}){
    const marketRows=STATE.data?.market?.rows||[];
    return Object.fromEntries(Object.entries(rows||{}).map(([symbol,item])=>{const sector=marketRows.find(row=>row.symbol===symbol)?.sector||item?.sector||'—';return [symbol,{symbol,sector,analysis_model:sector==='Banking'?'banking':'corporate',source:item?.source||'',provider:item?.provider||'',status:item?.status||'partial',source_as_of:item?.source_as_of||null,coverage:item?.coverage||{},warnings:item?.warnings||[],annual:buildFreq(item?.reports||{}),quarterly:{series:{},asset_mix:{},report_availability:{}}}];}));
  };
  function syncSharedResources(){
    KNOWLEDGE=STATE.resources?.knowledge||null;GLOBAL=STATE.resources?.global||null;initBrand();injectAccuracy();ensureGlobalPanel();renderKnowledge();
  }
  initBrand();ensureKnowledgeRoute();injectAccuracy();ensureGlobalPanel();window.addEventListener('rootvalue:data',syncSharedResources);$$('.lang-toggle').forEach(b=>b.addEventListener('click',()=>setTimeout(syncSharedResources,0)));if(STATE.data)renderAll();syncSharedResources();
})();
