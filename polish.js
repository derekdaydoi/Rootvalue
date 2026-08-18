// Rootvalue product layer — brand, knowledge, data accuracy and resilient dashboard fallback.
(() => {
  const css=document.createElement('link');css.rel='stylesheet';css.href='rootvalue-v2.css';document.head.appendChild(css);

  Object.assign(I18N.vi,{
    'brand.tag':'From zero to wealth.','nav.overview':'Dashboard','nav.overview.short':'Dashboard','nav.knowledge':'Kiến thức','nav.knowledge.short':'Kiến thức',
    'missing.interbank_rate':'Lãi suất liên ngân hàng','missing.policy_rate':'Lãi suất điều hành','missing.omo':'Nghiệp vụ thị trường mở','missing.credit':'Tăng trưởng tín dụng','missing.money_supply':'Cung tiền M2','missing.cpi':'CPI','missing.exchange_rate':'Tỷ giá NHNN'
  });
  Object.assign(I18N.en,{
    'brand.tag':'From zero to wealth.','nav.overview':'Dashboard','nav.overview.short':'Dashboard','nav.knowledge':'Knowledge','nav.knowledge.short':'Knowledge',
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
  const esc=(v)=>String(v??'').replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
  const rich=(v)=>esc(v).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
  const safeFetch=async(path)=>{try{const r=await fetch(`${path}?t=${Date.now()}`,{cache:'no-store'});return r.ok?await r.json():null}catch(_){return null}};
  const brandMarkup=()=>`<div class="rv-brand"><img class="rv-logo-mark" src="assets/rootvalue-mark.svg" alt="Rootvalue"><div class="rv-brand-copy"><div class="rv-brand-word"><span class="root">ROOT</span><span class="value">VALUE</span></div><div class="rv-brand-tag">From zero to wealth.</div></div></div>`;

  function initBrand(){
    const lock=$('.brand-lockup');if(lock)lock.innerHTML=brandMarkup();
    const mobile=$('.mobile-head .brand-word');if(mobile)mobile.outerHTML=brandMarkup();
    const side=$('.sidebar');if(side&&!$('.rv-copyright',side))side.insertAdjacentHTML('beforeend',`<div class="rv-copyright">© 2026 <strong>derekdaydoi</strong><br>${txt('Rootvalue · Dữ liệu trước nhận định.','Rootvalue · Evidence before opinion.')}</div>`);
    const main=$('.main');if(main&&!$('.rv-page-footer',main))main.insertAdjacentHTML('beforeend',`<footer class="rv-page-footer"><span>Rootvalue · From zero to wealth.</span><span>© 2026 derekdaydoi</span></footer>`);
  }

  let KNOWLEDGE=null;let KNOWLEDGE_TAB='library';let GLOBAL=null;
  function ensureKnowledgeRoute(){
    const side=$('.side-nav');
    if(side&&!$('[data-route="knowledge"]',side))side.insertAdjacentHTML('beforeend',`<button class="nav-item" data-route="knowledge"><span>06</span><b data-i18n="nav.knowledge">${txt('Kiến thức','Knowledge')}</b></button>`);
    const mobile=$('.mobile-nav');
    if(mobile&&!$('[data-route="knowledge"]',mobile))mobile.insertAdjacentHTML('beforeend',`<button class="mobile-nav-item" data-route="knowledge"><b>06</b><span data-i18n="nav.knowledge.short">${txt('Kiến thức','Knowledge')}</span></button>`);
    const main=$('.main');
    if(main&&!$('[data-screen="knowledge"]',main)){
      const footer=$('.rv-page-footer',main);
      const screen=document.createElement('section');screen.className='screen';screen.dataset.screen='knowledge';screen.innerHTML='<div id="rvKnowledgeRoot"></div>';
      main.insertBefore(screen,footer||null);
    }
    $$('[data-route="knowledge"]').forEach(btn=>btn.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();openKnowledge();}));
    $$('[data-route]:not([data-route="knowledge"])').forEach(btn=>btn.addEventListener('click',()=>{const s=$('[data-screen="knowledge"]');if(s)s.classList.remove('active');}));
  }
  function openKnowledge(){
    STATE.route='knowledge';$$('.screen').forEach(s=>s.classList.toggle('active',s.dataset.screen==='knowledge'));$$('.nav-item,.mobile-nav-item').forEach(b=>b.classList.toggle('active',b.dataset.route==='knowledge'));renderKnowledge();window.scrollTo({top:0,behavior:'smooth'});
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
    root.innerHTML=`<button class="rv-back-btn" id="rvKnowledgeBack">← ${txt('Quay lại','Back')}</button><article class="rv-article"><div class="eyebrow">${esc(isBlog?txt('BÀI VIẾT','ARTICLE'):(STATE.lang==='vi'?item.category_vi:item.category_en))}</div><h1>${esc(title)}</h1>${isBlog&&item.image?`<img src="${esc(item.image)}" alt="${esc(title)}">`:''}${blocks.map(renderBlock).join('')}</article>`;
    $('#rvKnowledgeBack').onclick=()=>renderKnowledge();
  }
  function renderKnowledge(){
    const root=$('#rvKnowledgeRoot');if(!root)return;if(!KNOWLEDGE){root.innerHTML=`<div class="notice">${txt('Đang tải thư viện kiến thức…','Loading knowledge library…')}</div>`;return;}
    const topics=KNOWLEDGE.topics||[],blogs=KNOWLEDGE.blogs||[];
    root.innerHTML=`<div class="rv-knowledge-hero"><div class="rv-knowledge-hero-copy"><div class="eyebrow">${txt('ROOTVALUE KNOWLEDGE','ROOTVALUE KNOWLEDGE')}</div><h1>${txt('Kiến thức','Knowledge')}</h1><p>${txt('Thư viện nền tảng về dòng tiền Việt Nam, công cụ NHNN, bảng cân đối và kinh tế vĩ mô. Mục tiêu là lưu framework và dữ kiện để dùng lại khi phân tích, không biến kiến thức thành tín hiệu mua bán.','A working library for Vietnam money flows, SBV tools, balance sheets and macro. It stores reusable frameworks and evidence, not buy/sell signals.')}</p></div><img src="assets/vietnam-money-flow.svg" alt="Vietnam money-flow map"></div><div class="rv-knowledge-tabs"><button class="rv-knowledge-tab ${KNOWLEDGE_TAB==='library'?'active':''}" data-ktab="library">${txt('Thư viện','Library')}</button><button class="rv-knowledge-tab ${KNOWLEDGE_TAB==='blog'?'active':''}" data-ktab="blog">${txt('Bài viết','Articles')}</button></div><div id="rvKnowledgeBody"></div>`;
    $$('[data-ktab]',root).forEach(b=>b.onclick=()=>{KNOWLEDGE_TAB=b.dataset.ktab;renderKnowledge()});
    const body=$('#rvKnowledgeBody');
    if(KNOWLEDGE_TAB==='blog')body.innerHTML=`<div class="rv-blog-list">${blogs.map(x=>`<article class="blog-card" data-blog="${esc(x.id)}"><img src="${esc(x.image||'assets/vietnam-money-flow.svg')}" alt=""><div class="body"><div class="eyebrow">${esc(x.date||'')}</div><h3>${esc(STATE.lang==='vi'?x.title_vi:x.title_en)}</h3><p>${esc(STATE.lang==='vi'?x.excerpt_vi:x.excerpt_en)}</p></div></article>`).join('')}</div>`;
    else body.innerHTML=`<div class="rv-knowledge-grid">${topics.map((x,i)=>`<article class="knowledge-card ${i===0?'wide':''}" data-topic="${esc(x.id)}"><div class="eyebrow">${esc(STATE.lang==='vi'?x.category_vi:x.category_en)}</div><h2>${esc(STATE.lang==='vi'?x.title_vi:x.title_en)}</h2><p>${esc(STATE.lang==='vi'?x.summary_vi:x.summary_en)}</p></article>`).join('')}</div>`;
    $$('[data-topic]',body).forEach(el=>el.onclick=()=>renderArticle(topics.find(x=>x.id===el.dataset.topic),false));$$('[data-blog]',body).forEach(el=>el.onclick=()=>renderArticle(blogs.find(x=>x.id===el.dataset.blog),true));
  }

  function formatGlobal(key,node){const v=Number(node?.latest);if(!Number.isFinite(v))return'N/A';if(key==='fed_total_assets')return `$${(v/1e6).toFixed(2)}T`;if(key==='fed_overnight_rrp')return `$${v.toFixed(1)}B`;if(['fed_funds_effective','us_2y','us_10y'].includes(key))return `${v.toFixed(2)}%`;if(key==='wti')return `$${v.toFixed(1)}`;return v.toFixed(2)}
  function ensureGlobalPanel(){
    const money=$('[data-screen="money"]');if(!money)return;let panel=$('#rvGlobalPanel');if(!panel){panel=document.createElement('article');panel.id='rvGlobalPanel';panel.className='rv-global-panel';const flow=$('.flow-map',money);money.insertBefore(panel,flow||money.firstChild);}renderGlobal();renderReactionInputs();
  }
  function renderGlobal(){
    const root=$('#rvGlobalPanel');if(!root)return;if(!GLOBAL){root.innerHTML=`<div class="rv-global-head"><div><div class="eyebrow">${txt('BÊN NGOÀI','EXTERNAL')}</div><h2>${txt('Fed & điều kiện tài chính toàn cầu','Fed & global financial conditions')}</h2></div><span class="rv-global-note">${txt('Đang chờ data/global.json','Waiting for data/global.json')}</span></div>`;return;}
    const s=GLOBAL.series||{};const keys=['fed_funds_effective','fed_total_assets','fed_overnight_rrp','broad_dollar','us_10y'];
    const cards=keys.map(k=>{const n=s[k]||{};return `<div class="rv-global-metric"><span>${esc(n.label||k)}</span><strong>${esc(formatGlobal(k,n))}</strong><small>${esc(n.as_of||'N/A')} · ${esc(n.frequency||'')}</small></div>`}).join('');
    const news=(GLOBAL.news||[]).slice(0,6).map(n=>`<div class="rv-news-item"><span class="src">${esc(n.source)}</span><a href="${esc(n.url||'#')}" target="_blank" rel="noopener">${esc(n.title)}</a><time>${esc(n.published||'')}</time></div>`).join('');
    root.innerHTML=`<div class="rv-global-head"><div><div class="eyebrow">${txt('BÊN NGOÀI','EXTERNAL')}</div><h2>${txt('Fed & điều kiện tài chính toàn cầu','Fed & global financial conditions')}</h2></div><span class="rv-global-note">${esc(GLOBAL.freshness_class||'')}</span></div><div class="rv-global-grid">${cards}</div><div class="rv-news-list">${news||`<div class="muted">${txt('Chưa có headline từ nguồn chính thức.','No official-source headlines yet.')}</div>`}</div>`;
    const fed=s.fed_funds_effective,broad=s.broad_dollar;const external=$('#externalValue');if(external)external.textContent=`Fed ${formatGlobal('fed_funds_effective',fed)} · USD ${formatGlobal('broad_dollar',broad)}`;
  }
  function renderReactionInputs(){
    const status=$('#reactionStatus'),missing=$('#missingCore');if(!status||!missing)return;let grid=$('#rvReactionGrid');if(!grid){grid=document.createElement('div');grid.id='rvReactionGrid';grid.className='rv-reaction-grid';missing.parentNode.insertBefore(grid,missing);}const metrics=STATE.data?.macro?.metrics||[];const has=(k)=>metrics.some(x=>x.key===k&&x.value!=null);const globalReady=GLOBAL?.status==='ok'||GLOBAL?.status==='partial';const items=[
      [txt('Ngoại lực','External'),globalReady,globalReady?txt('Fed/USD đã nối','Fed/USD wired'):txt('thiếu','missing')],
      ['OMO',has('sbv_omo_awarded'),has('sbv_omo_awarded')?txt('có snapshot chính thức','official snapshot'):txt('thiếu','missing')],
      [txt('M2 / tiền gửi','M2 / deposits'),has('sbv_m2_growth'),has('sbv_m2_growth')?txt('có snapshot chính thức','official snapshot'):txt('thiếu','missing')],
      [txt('Liên ngân hàng','Interbank'),false,txt('thiếu chuỗi lịch sử','history missing')],
      [txt('Tỷ giá NHNN','SBV FX'),false,txt('thiếu chuỗi lịch sử','history missing')],
      [txt('Tín dụng + CPI','Credit + CPI'),false,txt('thiếu chuỗi lịch sử','history missing')]
    ];grid.innerHTML=items.map(x=>`<div class="rv-reaction-cell ${x[1]?'ok':'missing'}"><span>${esc(x[0])}</span><strong>${esc(x[2])}</strong></div>`).join('');const ready=items.filter(x=>x[1]).length;status.textContent=`${ready}/${items.length} ${txt('nhóm đầu vào có dữ liệu','input groups observed')}`;status.className=`pill ${ready===items.length?'ok':'warning'}`;
  }

  function injectAccuracy(){
    const screen=$('[data-screen="overview"]');if(!screen||$('#rvAccuracyPanel',screen))return;const head=$('.screen-head',screen);const box=document.createElement('article');box.id='rvAccuracyPanel';box.className='rv-accuracy-panel';box.innerHTML=`<div class="rv-accuracy-head"><div><div class="eyebrow">${txt('ĐỘ CHÍNH XÁC TRƯỚC TỐC ĐỘ','ACCURACY BEFORE SPEED')}</div><h3>${txt('Rootvalue hiện là near real time, không phải real time','Rootvalue is near-real-time, not real-time')}</h3><p>${txt('Mỗi dataset giữ hai thời điểm riêng: thời điểm nguồn công bố và thời điểm Rootvalue lấy dữ liệu. Dữ liệu chậm theo bản chất nguồn sẽ không được gắn nhãn real time.','Each dataset keeps the source observation date separate from Rootvalue fetch time. Data that are inherently delayed are never labelled real-time.')}</p></div><span class="rv-freshness-badge">Near real time</span></div><div class="rv-freshness-grid"><div class="rv-freshness-item"><b>${txt('Thị trường','Market')}</b><span>${txt('Sau đóng cửa ~16:20 ICT','After close ~16:20 ICT')}</span></div><div class="rv-freshness-item"><b>Fed / Global</b><span>${txt('Poll hàng giờ · theo nhịp nguồn','Hourly poll · source cadence')}</span></div><div class="rv-freshness-item"><b>NHNN</b><span>${txt('Capture hằng ngày · nguồn có thể tháng/tuần/sự kiện','Daily capture · source may be monthly/weekly/event')}</span></div><div class="rv-freshness-item"><b>${txt('BCTC','Financials')}</b><span>${txt('Check hằng ngày · bản chất quý/năm','Daily check · quarterly/annual source')}</span></div></div>`;if(head)head.insertAdjacentElement('afterend',box);else screen.prepend(box);
  }

  function payloadRows(report){const d=report?.data||{};const cols=d.columns||[];return (d.rows||[]).map(row=>Object.fromEntries(cols.map((c,i)=>[String(c),row[i]])))}
  function pickRow(rows,ids){for(const id of ids){const r=rows.find(x=>String(x.item_id||x.id||'').trim()===id);if(r)return r}return null}
  function series(row){if(!row)return[];return Object.entries(row).filter(([k,v])=>/^20\d{2}/.test(k)&&Number.isFinite(Number(v))).map(([period,value])=>({period,value:Number(value)})).sort((a,b)=>String(a.period).localeCompare(String(b.period)))}
  function combine(a,b,fn){const A=new Map(a.map(x=>[x.period,x.value])),B=new Map(b.map(x=>[x.period,x.value]));return [...new Set([...A.keys(),...B.keys()])].sort().flatMap(p=>A.has(p)&&B.has(p)?[{period:p,value:fn(A.get(p),B.get(p))}]:[])}
  function buildFreq(reports){const inc=payloadRows(reports?.income_statement),cf=payloadRows(reports?.cash_flow),bs=payloadRows(reports?.balance_sheet);const r={};r.revenue=series(pickRow(inc,['net_revenue','revenue']));r.cogs=series(pickRow(inc,['cost_of_goods_sold']));r.gross_profit=series(pickRow(inc,['gross_profit']));r.operating_profit=series(pickRow(inc,['operating_profit']));r.net_profit=series(pickRow(inc,['profit_after_tax_for_shareholders_of_parent_company','net_profit']));r.interest_expense=series(pickRow(inc,['of_which_interest_expense','interest_expense']));r.cfo=series(pickRow(cf,['net_cash_flows_from_operating_activities','net_cash_flow_from_operating_activities']));r.capex=series(pickRow(cf,['purchase_of_fixed_assets','purchase_of_fixed_assets_and_other_long_term_assets']));r.fcf=combine(r.cfo,r.capex,(x,y)=>x+y);r.total_assets=series(pickRow(bs,['total_assets','total_asset']));r.current_assets=series(pickRow(bs,['current_assets','total_current_assets']));r.current_liabilities=series(pickRow(bs,['current_liabilities','total_current_liabilities']));r.cash=series(pickRow(bs,['cash_and_cash_equivalents','cash']));r.receivables=series(pickRow(bs,['short_term_receivables','receivables']));r.inventory=series(pickRow(bs,['inventories','inventory']));r.ppe=series(pickRow(bs,['fixed_assets','tangible_fixed_assets','property_plant_equipment']));r.cip=series(pickRow(bs,['construction_in_progress','construction_in_progress_cost']));r.payables=series(pickRow(bs,['trade_payables','short_term_trade_payables']));r.short_debt=series(pickRow(bs,['short_term_borrowings','short_term_debt','short_term_borrowings_and_finance_lease_liabilities']));r.long_debt=series(pickRow(bs,['long_term_borrowings','long_term_debt','long_term_borrowings_and_finance_lease_liabilities']));r.total_debt=(r.short_debt.length&&r.long_debt.length)?combine(r.short_debt,r.long_debt,(x,y)=>x+y):(r.short_debt.length?r.short_debt:r.long_debt);r.nwc=combine(r.current_assets,r.current_liabilities,(x,y)=>x-y);r.gross_margin=combine(r.gross_profit,r.revenue,(x,y)=>y?x/y:0);r.net_margin=combine(r.net_profit,r.revenue,(x,y)=>y?x/y:0);r.cfo_to_profit=combine(r.cfo,r.net_profit,(x,y)=>y?x/y:0);return {series:r,asset_mix:{cash:r.cash,receivables:r.receivables,inventory:r.inventory,ppe:r.ppe,cip:r.cip,other:[]},report_availability:{balance_sheet:!!bs.length,income_statement:!!inc.length,cash_flow:!!cf.length}}}
  async function dashboardFallback(){
    if(RV_SUPP.dashboard?.companies&&Object.keys(RV_SUPP.dashboard.companies).length)return;const watch=await safeFetch('config/watchlist.json');if(!watch)return;const sector=new Map((watch.symbols||[]).map(x=>[x.symbol,x.sector]));const symbols=watch.fundamental_symbols||[];const entries=await Promise.all(symbols.map(async sym=>[sym,await safeFetch(`data/foundation/companies/${sym}.json`)]));const companies={};for(const [sym,raw] of entries){if(!raw)continue;companies[sym]={symbol:sym,sector:sector.get(sym)||'',analysis_model:sector.get(sym)==='Banking'?'banking':'generic',source:raw.source,coverage:raw.coverage||{},warnings:raw.warnings||[],annual:buildFreq(raw.reports?.annual||{}),quarterly:buildFreq(raw.reports?.quarterly||{})}}RV_SUPP.dashboard={schema_version:'runtime-fallback',companies};if(Object.keys(companies).length)renderCompany();
  }

  async function hydrate(){
    initBrand();ensureKnowledgeRoute();injectAccuracy();ensureGlobalPanel();
    [KNOWLEDGE,GLOBAL]=await Promise.all([safeFetch('content/knowledge.json'),safeFetch('data/global.json')]);renderKnowledge();renderGlobal();renderReactionInputs();await dashboardFallback();
    $$('.lang-toggle').forEach(b=>b.addEventListener('click',()=>setTimeout(()=>{initBrand();renderKnowledge();renderGlobal();renderReactionInputs();injectAccuracy();},0)));
  }
  if(STATE.data)renderAll();hydrate();
})();
