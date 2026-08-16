// Rootvalue analysis layer — dynamic story charts + Vietnam monetary stock-flow map.
const RV_SUPP={market:null,dashboard:null};
STATE.companyPeriod=STATE.companyPeriod||'annual';
STATE.companyView=STATE.companyView||'dashboard';
STATE.companySector=STATE.companySector||null;

function rvText(vi,en){return STATE.lang==='vi'?vi:en;}
function rvNum(v){return Number.isFinite(Number(v))?Number(v):null;}
function rvCompact(v){
  const n=rvNum(v);if(n==null)return 'N/A';const a=Math.abs(n);
  if(a>=1e12)return `${fmt(n/1e12,1)} ${rvText('nghìn tỷ','tn VND')}`;
  if(a>=1e9)return `${fmt(n/1e9,1)} ${rvText('tỷ','bn VND')}`;
  if(a>=1e6)return `${fmt(n/1e6,1)} ${rvText('triệu','mn VND')}`;
  return fmt(n,1);
}
function rvPct(v){const n=rvNum(v);return n==null?'N/A':`${fmt(n*100,1)}%`;}
function rvSeriesMap(series=[]){return new Map((series||[]).map(x=>[String(x.period),rvNum(x.value)]));}
function rvPeriodKey(p){const s=String(p||'');const y=Number((s.match(/20\d{2}/)||['0'])[0]);const q=Number((s.match(/(?:Q|Quý\s*)([1-4])/i)||[])[1]||0);return y*10+q;}
function rvPeriods(defs){return [...new Set(defs.flatMap(d=>(d.data||[]).map(x=>String(x.period))))].sort((a,b)=>rvPeriodKey(a)-rvPeriodKey(b));}
function rvEmpty(text){return `<div class="chart-empty">${escapeHtml(text||rvText('Chưa có dữ liệu cho chart này.','No data for this chart yet.'))}</div>`;}
function rvLegend(defs){return `<div class="chart-legend">${defs.map((d,i)=>`<span><i class="legend-swatch s${i%5}"></i>${escapeHtml(d.label)}</span>`).join('')}</div>`;}

function rvChart(defs,{percent=false}={}){
  const clean=defs.filter(d=>(d.data||[]).some(x=>rvNum(x.value)!=null));
  if(!clean.length)return rvEmpty();
  const periods=rvPeriods(clean);if(!periods.length)return rvEmpty();
  const maps=clean.map(d=>rvSeriesMap(d.data));
  const values=[];maps.forEach(m=>periods.forEach(p=>{const v=m.get(p);if(v!=null)values.push(v)}));
  if(!values.length)return rvEmpty();
  let min=Math.min(...values),max=Math.max(...values);if(min>0)min=0;if(max<0)max=0;if(max===min){max=min+1}
  const W=620,H=220,L=58,R=12,T=15,B=30,plotW=W-L-R,plotH=H-T-B;
  const x=i=>L+(periods.length===1?plotW/2:(i/(periods.length-1))*plotW);
  const y=v=>T+((max-v)/(max-min))*plotH;
  const formatAxis=v=>percent?`${fmt(v*100,0)}%`:rvCompact(v).replace(/ VND$/,'');
  let svg=`<svg class="rv-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">`;
  for(let i=0;i<4;i++){const val=max-(max-min)*(i/3);const yy=y(val);svg+=`<line class="rv-grid-line" x1="${L}" x2="${W-R}" y1="${yy}" y2="${yy}"/><text class="rv-axis-text" x="${L-7}" y="${yy+3}" text-anchor="end">${escapeHtml(formatAxis(val))}</text>`;}
  const labelEvery=Math.max(1,Math.ceil(periods.length/7));periods.forEach((p,i)=>{if(i%labelEvery===0||i===periods.length-1)svg+=`<text class="rv-axis-text" x="${x(i)}" y="${H-8}" text-anchor="middle">${escapeHtml(p)}</text>`});
  clean.forEach((d,si)=>{const m=maps[si];let seg=[];periods.forEach((p,i)=>{const v=m.get(p);if(v==null){if(seg.length>1)svg+=`<polyline class="rv-line s${si%5}" points="${seg.join(' ')}"/>`;seg=[];return;}seg.push(`${x(i)},${y(v)}`);svg+=`<circle class="rv-dot s${si%5}" cx="${x(i)}" cy="${y(v)}" r="2.6"/>`;});if(seg.length>1)svg+=`<polyline class="rv-line s${si%5}" points="${seg.join(' ')}"/>`;});
  svg+='</svg>';return rvLegend(clean)+svg;
}

function rvAssetBars(assetMix={}){
  const names=[
    ['cash',rvText('Tiền','Cash')],['receivables',rvText('Phải thu','Receivables')],['inventory',rvText('Tồn kho','Inventory')],
    ['ppe',rvText('TSCĐ','Fixed assets')],['cip',rvText('XDCB dở dang','CIP')],['other',rvText('Khác','Other')]
  ];
  const defs=names.map(([key,label])=>({key,label,data:assetMix[key]||[]})).filter(d=>d.data.length);
  if(!defs.length)return rvEmpty(rvText('Chưa có bảng cân đối kế toán để bóc tách tài sản.','Balance-sheet data is not available for asset decomposition.'));
  const periods=rvPeriods(defs);const maps=defs.map(d=>rvSeriesMap(d.data));
  const bars=periods.map(p=>{const vals=maps.map(m=>Math.max(m.get(p)||0,0));const total=vals.reduce((a,b)=>a+b,0);return `<div class="asset-col"><div class="asset-stack">${vals.map((v,i)=>`<div class="asset-seg s${i}" style="height:${total?Math.max(0,(v/total)*100):0}%" title="${escapeHtml(defs[i].label)}: ${escapeHtml(rvCompact(v))}"></div>`).join('')}</div><span class="asset-label">${escapeHtml(p)}</span></div>`}).join('');
  return rvLegend(defs)+`<div class="asset-bars">${bars}</div>`;
}
function rvStoryCard(step,title,subtitle,defs,opts={}){return `<article class="story-card ${opts.wide?'wide':''}"><div class="story-card-head"><div><span class="story-step">${escapeHtml(step)}</span><h3>${escapeHtml(title)}</h3><p>${escapeHtml(subtitle)}</p></div></div>${opts.asset?rvAssetBars(opts.asset):rvChart(defs,opts)}</article>`;}

function ensureCompanyShell(){
  const screen=$('[data-screen="company"]');if(!screen||screen.dataset.analysisShell==='1')return;screen.dataset.analysisShell='1';
  screen.innerHTML=`<div class="company-analysis-shell">
    <div class="company-hero"><div><div class="eyebrow">${rvText('TỪ DƯỚI LÊN','BOTTOM-UP')}</div><h1 id="companyBigSymbol">—</h1><p class="lead" id="companyBigLead"></p></div>
      <div class="company-filter-grid"><label class="big-select"><span>${rvText('Ngành','Sector')}</span><select id="sectorSelect"></select></label><label class="big-select"><span>${rvText('Doanh nghiệp','Company')}</span><select id="companySelectLarge"></select></label><div class="period-control"><span>${rvText('Kỳ phân tích','Period')}</span><div class="period-toggle"><button class="period-btn" data-cperiod="annual">${rvText('Năm','Annual')}</button><button class="period-btn" data-cperiod="quarterly">${rvText('Quý','Quarterly')}</button></div></div></div>
    </div>
    <div class="company-meta-line" id="companyMeta"></div>
    <section class="suggestion-block"><div class="suggestion-title"><div><span class="eyebrow">${rvText('GỢI Ý ĐIỀU TRA','INVESTIGATION PICKS')}</span><h2>${rvText('Dẫn dắt ngành & chuyển biến bất thường','Sector leaders & unusual movers')}</h2></div><small>${rvText('3 dẫn dắt + tối đa 2 bất thường · tự động từ market-flow','3 leaders + up to 2 unusual movers · generated from market flow')}</small></div><div class="suggestion-grid" id="companySuggestions"></div></section>
    <div class="company-view-tabs"><button class="company-view-btn" data-cview="dashboard">${rvText('Dashboard câu chuyện','Story dashboard')}</button><button class="company-view-btn" data-cview="raw">${rvText('BCTC gốc','Raw statements')}</button></div>
    <div class="company-view" id="companyDashboardView"><div class="story-header"><div><span class="eyebrow">${rvText('CHUỖI DỮ LIỆU','DATA STORY')}</span><h2>${rvText('Từ quy mô → lợi nhuận → tiền → vốn lưu động → nợ → tài sản','Scale → earnings → cash → working capital → debt → assets')}</h2></div><p>${rvText('Chỉ vẽ dữ liệu đã lấy được. Không chèn nhận định hay số giả.','Charts only use retrieved facts. No synthetic values or investment opinions are inserted.')}</p></div><div class="story-grid" id="companyDashboardCharts"></div></div>
    <div class="company-view" id="companyRawView"><div id="companyNotice"></div><div class="history-strip" id="historyCoverage"></div><div class="raw-head"><div class="report-tabs" id="reportTabs"></div></div><div class="table-wrap report-wrap"><table class="data-table financial-table" id="financialTable"></table></div></div>
  </div>`;
}

function rvDashboardCompanies(){return RV_SUPP.dashboard?.companies||{};}
function rvAllSectors(){
  const set=new Set();Object.values(rvDashboardCompanies()).forEach(c=>c?.sector&&set.add(c.sector));
  Object.keys(STATE.data?.market?.selection_by_sector||{}).forEach(x=>set.add(x));
  (STATE.data?.market?.rows||[]).forEach(r=>r?.sector&&set.add(r.sector));return [...set].sort();
}
function rvSymbolsForSector(sector){
  const set=new Set();Object.values(rvDashboardCompanies()).forEach(c=>{if(!sector||c.sector===sector)set.add(c.symbol)});
  (STATE.data?.market?.rows||[]).forEach(r=>{if(!sector||r.sector===sector)set.add(r.symbol)});return [...set].sort();
}
function rvSuggestionRows(sector){
  const by=STATE.data?.market?.selection_by_sector||{};if(by[sector]?.length)return by[sector];
  const rows=(STATE.data?.market?.rows||[]).filter(r=>r.sector===sector);if(!rows.length)return [];
  const ranked=[...rows].sort((a,b)=>(a.sector_rank??999)-(b.sector_rank??999));const leaders=ranked.slice(0,3).map(x=>({...x,selection_type:'Leader'}));const rest=ranked.slice(3).sort((a,b)=>Math.abs(b.rank_delta||0)-Math.abs(a.rank_delta||0)).slice(0,2).map(x=>({...x,selection_type:'Abnormal'}));return [...leaders,...rest];
}
function rvRenderSuggestions(sector){
  const root=$('#companySuggestions');if(!root)return;const dash=rvDashboardCompanies();const rows=rvSuggestionRows(sector);
  if(!rows.length){root.innerHTML=rvEmpty(rvText('Market-flow chưa có dữ liệu cho ngành này.','Market-flow has no data for this sector yet.'));return;}
  root.innerHTML=rows.map(r=>{const available=!!dash[r.symbol];const leader=r.selection_type==='Leader';return `<button class="suggestion-card ${available?'':'unavailable'} ${r.symbol===STATE.company?'active':''}" data-pick-company="${escapeHtml(r.symbol)}"><div class="suggestion-top"><strong>${escapeHtml(r.symbol)}</strong><span class="suggestion-type">${leader?rvText('Dẫn dắt','Leader'):rvText('Bất thường','Unusual')}</span></div><div class="suggestion-state">${escapeHtml(stateLabel(r.state||'Neutral'))}${available?'':` · ${rvText('chưa tải BCTC','financials not loaded')}`}</div><div class="suggestion-stats"><span>${rvText('Hạng','Rank')} <b>#${r.sector_rank??r.rank_current??'—'}</b></span><span>Δ <b class="${cls(r.rank_delta)}">${signed(r.rank_delta,0)}</b></span></div></button>`}).join('');
  $$('[data-pick-company]',root).forEach(btn=>btn.onclick=()=>{STATE.company=btn.dataset.pickCompany;renderCompany();});
}

function rvRenderDashboard(company){
  const root=$('#companyDashboardCharts');if(!root)return;if(!company){root.innerHTML=rvEmpty(rvText('Doanh nghiệp này chưa được backfill BCTC vào Data Foundation.','This company has not been backfilled into the financial-data foundation yet.'));return;}
  const freq=company[STATE.companyPeriod]||{};const s=freq.series||{};
  if(company.analysis_model==='banking'){
    root.innerHTML=`<article class="story-card wide"><div class="story-card-head"><div><span class="story-step">BANK MODEL</span><h3>${rvText('Ngân hàng cần bộ chart riêng','Banks require a separate analytical model')}</h3><p>${rvText('NWC và Net Debt/EBITDA không có ý nghĩa như doanh nghiệp thường. Rootvalue sẽ dùng NIM, CASA, tín dụng, huy động, NPL, LLR khi source được nối.','Generic NWC and Net Debt/EBITDA are not meaningful for banks. Rootvalue will use NIM, CASA, credit, deposits, NPL and LLR once those feeds are normalized.')}</p></div></div>${rvChart([{label:rvText('Lợi nhuận sau thuế','Net profit'),data:s.net_profit||[]},{label:rvText('CFO','CFO'),data:s.cfo||[]}])}</article>`;return;
  }
  const cards=[];
  cards.push(rvStoryCard('01',rvText('Quy mô & lợi nhuận','Scale & earnings'),rvText('Doanh thu, lợi nhuận gộp, lợi nhuận ròng','Revenue, gross profit, net profit'),[
    {label:rvText('Doanh thu','Revenue'),data:s.revenue||[]},{label:rvText('LN gộp','Gross profit'),data:s.gross_profit||[]},{label:rvText('LN ròng','Net profit'),data:s.net_profit||[]}
  ]));
  cards.push(rvStoryCard('02',rvText('Bóc tách lợi nhuận','Profit decomposition'),rvText('Doanh thu → giá vốn → vận hành → lợi nhuận ròng','Revenue → COGS → operating profit → net profit'),[
    {label:rvText('Doanh thu','Revenue'),data:s.revenue||[]},{label:rvText('Giá vốn','COGS'),data:s.cogs||[]},{label:rvText('LN vận hành','Operating profit'),data:s.operating_profit||[]},{label:rvText('LN ròng','Net profit'),data:s.net_profit||[]}
  ]));
  cards.push(rvStoryCard('03',rvText('Lợi nhuận có thành tiền?','Does profit become cash?'),rvText('Lợi nhuận ròng, CFO và FCF','Net profit, CFO and FCF'),[
    {label:rvText('LN ròng','Net profit'),data:s.net_profit||[]},{label:'CFO',data:s.cfo||[]},{label:'FCF',data:s.fcf||[]}
  ]));
  cards.push(rvStoryCard('04',rvText('Vốn lưu động','Working capital'),rvText('NWC, phải thu và tồn kho','NWC, receivables and inventory'),[
    {label:'NWC',data:s.nwc||[]},{label:rvText('Operating NWC','Operating NWC'),data:s.operating_nwc||[]},{label:rvText('Phải thu','Receivables'),data:s.receivables||[]},{label:rvText('Tồn kho','Inventory'),data:s.inventory||[]}
  ]));
  cards.push(rvStoryCard('05',rvText('Nợ & chi phí vốn','Debt & financing cost'),rvText('Nợ ngắn hạn, dài hạn, tổng nợ và chi phí lãi','Short debt, long debt, total debt and interest expense'),[
    {label:rvText('Nợ ngắn hạn','Short debt'),data:s.short_debt||[]},{label:rvText('Nợ dài hạn','Long debt'),data:s.long_debt||[]},{label:rvText('Tổng nợ','Total debt'),data:s.total_debt||[]},{label:rvText('Chi phí lãi','Interest expense'),data:s.interest_expense||[]}
  ]));
  cards.push(rvStoryCard('06',rvText('Biên lợi nhuận','Margins'),rvText('Biên gộp và biên ròng theo thời gian','Gross and net margin through time'),[
    {label:rvText('Biên gộp','Gross margin'),data:s.gross_margin||[]},{label:rvText('Biên ròng','Net margin'),data:s.net_margin||[]}
  ],{percent:true}));
  cards.push(rvStoryCard('07',rvText('Tài sản đang nằm ở đâu?','Where are the assets?'),rvText('Cơ cấu tài sản theo từng kỳ; tổng mỗi cột = 100%','Asset composition by period; each column sums to 100%'),[],{wide:true,asset:freq.asset_mix||{}}));
  root.innerHTML=cards.join('');
}

renderCompany=function(){
  ensureCompanyShell();const dash=rvDashboardCompanies();const sectors=rvAllSectors();
  if(!STATE.company&&Object.keys(dash).length){STATE.company=Object.values(dash).find(c=>c.analysis_model!=='banking')?.symbol||Object.keys(dash)[0];}
  const current=dash[STATE.company];if(!STATE.companySector)STATE.companySector=current?.sector||sectors[0]||'';
  const sectorSelect=$('#sectorSelect');sectorSelect.innerHTML=sectors.map(s=>`<option value="${escapeHtml(s)}" ${s===STATE.companySector?'selected':''}>${escapeHtml(sectorLabel(s))}</option>`).join('');sectorSelect.onchange=e=>{STATE.companySector=e.target.value;const available=rvSymbolsForSector(STATE.companySector);STATE.company=available.find(s=>dash[s])||available[0]||null;renderCompany();};
  const symbols=rvSymbolsForSector(STATE.companySector);if(STATE.company&&!symbols.includes(STATE.company)){STATE.company=symbols.find(s=>dash[s])||symbols[0]||null;}
  const companySelect=$('#companySelectLarge');companySelect.innerHTML=symbols.map(s=>`<option value="${escapeHtml(s)}" ${s===STATE.company?'selected':''}>${escapeHtml(s)}${dash[s]?'':` · ${rvText('chưa có BCTC','no financials')}`}</option>`).join('');companySelect.onchange=e=>{STATE.company=e.target.value;renderCompany();};
  $$('[data-cperiod]').forEach(btn=>{btn.classList.toggle('active',btn.dataset.cperiod===STATE.companyPeriod);btn.onclick=()=>{STATE.companyPeriod=btn.dataset.cperiod;renderCompany();}});
  $$('[data-cview]').forEach(btn=>{btn.classList.toggle('active',btn.dataset.cview===STATE.companyView);btn.onclick=()=>{STATE.companyView=btn.dataset.cview;renderCompany();}});
  $('#companyDashboardView').classList.toggle('active',STATE.companyView==='dashboard');$('#companyRawView').classList.toggle('active',STATE.companyView==='raw');
  const company=dash[STATE.company];const raw=STATE.data?.companies?.rows?.[STATE.company]||null;$('#companyBigSymbol').textContent=STATE.company||'—';$('#companyBigLead').textContent=company?`${escapeHtml(sectorLabel(company.sector))} · ${rvText('Dashboard tự động từ BCTC chuẩn hóa','Automated dashboard from normalized financial statements')}`:rvText('Mã này nằm trong market universe nhưng chưa được backfill BCTC.','This symbol is in the market universe but its financial statements have not been backfilled yet.');
  const cov=company?.coverage||raw?.coverage||{};const periods=cov.annual_periods||0;$('#companyMeta').innerHTML=`<span class="company-meta-chip ${periods<8?'warn':''}">${rvText('Độ phủ','Coverage')}: <strong>${periods}/8 ${rvText('năm','years')}</strong></span><span class="company-meta-chip">${rvText('Nguồn','Source')}: <strong>${escapeHtml(company?.source||raw?.source||'N/A')}</strong></span><span class="company-meta-chip">${rvText('Kỳ','Period')}: <strong>${STATE.companyPeriod==='annual'?rvText('Năm','Annual'):rvText('Quý','Quarterly')}</strong></span>`;
  rvRenderSuggestions(STATE.companySector);rvRenderDashboard(company);
  if(STATE.companyView==='raw'){
    $('#companyNotice').innerHTML=raw?notice(`${STATE.company} · ${rvText('độ phủ','coverage')}: ${raw?.coverage?.annual_periods??0}/8`):notice(rvText('BCTC chưa được tải cho mã này.','Financial statements are not loaded for this symbol.'),'warning');
    renderHistoryCoverage(raw);const tabs=$('#reportTabs');tabs.innerHTML=raw?REPORTS.map(k=>`<button class="report-tab ${STATE.report===k?'active':''}" data-report="${k}">${t(`report.${k}`)}</button>`).join(''):'';$$('[data-report]',tabs).forEach(btn=>btn.onclick=()=>{STATE.report=btn.dataset.report;renderCompany();});renderFinancialTable(raw?.reports?.[STATE.report]);
  }
};

const rvPreviousRenderMoney=renderMoney;
function rvActorCard(kicker,title,value,sub,primary=false){return `<article class="actor-card ${primary?'primary':''}"><span>${escapeHtml(kicker)}</span><h3>${escapeHtml(title)}</h3>${value?`<div class="actor-value">${value}</div><div class="actor-sub">${escapeHtml(sub||'')}</div>`:`<div class="actor-missing">${rvText('Chưa có chuỗi dữ liệu xác minh','Verified series not available yet')}</div>`}</article>`;}
function rvSystemDepth(){
  const screen=$('[data-screen="money"]');if(!screen)return;let root=$('#systemDepth');if(!root){root=document.createElement('section');root.id='systemDepth';root.className='system-depth';const flow=$('#flowMap');flow?.after(root);}
  const cur=STATE.data?.macro?.sbv_current||{};
  root.innerHTML=`<div class="system-depth-head"><div><span class="eyebrow">${rvText('STOCK–FLOW VIỆT NAM','VIETNAM STOCK–FLOW')}</span><h2>${rvText('Tiền đang nằm ở đâu và actor nào đang làm thay đổi thanh khoản?','Where is money held, and which actor is changing liquidity?')}</h2></div><p>${rvText('Phân biệt stock tiền, flow giao dịch và tác động lên bank reserves. Giá trị nào chưa có nguồn thì giữ N/A.','Separates money stocks, transaction flows and bank-reserve effects. Unverified fields remain N/A.')}</p></div>
  <div class="actor-grid">
    ${rvActorCard('01',rvText('NHNN','SBV'),cur.omo_awarded_bn_vnd!=null?`${fmt(cur.omo_awarded_bn_vnd,0)} ${rvText('tỷ OMO','bn VND OMO')}`:'',cur.omo_rate_pct!=null?`${rvText('Lãi suất','Rate')} ${fmt(cur.omo_rate_pct,2)}%`:'',true)}
    ${rvActorCard('02',rvText('Hệ thống ngân hàng','Banking system'),cur.m2_balance_bn_vnd!=null?`${rvCompact(cur.m2_balance_bn_vnd*1e9)}`:'',rvText('M2 quan sát; chưa phải bank reserves','Observed M2; bank reserves not yet available'))}
    ${rvActorCard('03',rvText('Người dân','Households'),cur.household_deposit_bn_vnd!=null?`${rvCompact(cur.household_deposit_bn_vnd*1e9)}`:'',cur.household_deposit_growth_ytd_pct!=null?`${rvText('Tăng YTD','YTD growth')} ${fmt(cur.household_deposit_growth_ytd_pct,2)}%`:'')}
    ${rvActorCard('04',rvText('Doanh nghiệp','Corporates'),cur.corp_deposit_bn_vnd!=null?`${rvCompact(cur.corp_deposit_bn_vnd*1e9)}`:'',cur.corp_deposit_growth_ytd_pct!=null?`${rvText('Tăng YTD','YTD growth')} ${fmt(cur.corp_deposit_growth_ytd_pct,2)}%`:'')}
    ${rvActorCard('05',rvText('Kho bạc','Treasury'),'','')}
    ${rvActorCard('06',rvText('Khu vực nước ngoài','Foreign sector'),'','')}
  </div>
  <div class="transmission-panel"><div class="transmission-title">${rvText('CƠ CHẾ TRUYỀN DẪN — dùng để đọc diễn biến, không phải dự báo','TRANSMISSION RULEBOOK — for reading the path, not a forecast')}</div>
    ${[
      [rvText('KBNN tăng số dư tại NHNN','Treasury balance at SBV rises'),rvText('Bank reserves giảm','Bank reserves fall'),rvText('Áp lực O/N tăng nếu NHNN không bù','O/N pressure rises unless SBV offsets')],
      [rvText('Chính phủ giải ngân','Government spending rises'),rvText('Bank reserves + tiền gửi tư nhân tăng','Bank reserves + private deposits rise'),rvText('Thanh khoản VND được bơm lại','VND liquidity is injected')],
      [rvText('NHNN bán USD','SBV sells USD'),rvText('Bank VND reserves giảm','Bank VND reserves fall'),rvText('O/N có xu hướng tăng nếu không có OMO bù','O/N tends to rise unless OMO offsets')],
      [rvText('O/N tăng rồi OMO tăng','O/N rises, then OMO rises'),rvText('NHNN cấp thanh khoản ngắn hạn','SBV supplies short-term liquidity'),rvText('Đây có thể là phản ứng với stress, không mặc định là easing','May be a response to stress; not automatically easing')],
      [rvText('Tín dụng tăng nhanh hơn huy động','Credit grows faster than deposits'),rvText('Funding gap tăng','Funding gap widens'),rvText('Lãi huy động / liên ngân hàng / nhu cầu OMO có thể tăng','Deposit/interbank rates or OMO demand may rise')],
      [rvText('Người dân mua cổ phiếu','Households buy equities'),rvText('Tiền gửi chuyển chủ sở hữu','Deposits change owner'),rvText('Asset allocation đổi; tổng deposits không tự động giảm','Asset allocation changes; aggregate deposits do not automatically fall')]
    ].map(r=>`<div class="transmission-row"><b>${escapeHtml(r[0])}</b><span class="transmission-arrow">→</span><span>${escapeHtml(r[1])}</span><span class="transmission-arrow">→</span><span>${escapeHtml(r[2])}</span></div>`).join('')}
  </div>`;
}
renderMoney=function(){rvPreviousRenderMoney();rvSystemDepth();};

async function rvFetchJson(path){try{const res=await fetch(`${path}?t=${Date.now()}`,{cache:'no-store'});if(!res.ok)return null;return await res.json();}catch(_){return null;}}
async function rvHydrateSupplemental(){
  const [market,dashboard]=await Promise.all([rvFetchJson('data/market.json'),rvFetchJson('data/company_dashboard.json')]);RV_SUPP.market=market;RV_SUPP.dashboard=dashboard;
  let n=0;while(!STATE.data&&n<40){await new Promise(r=>setTimeout(r,100));n++;}
  if(!STATE.data)return;if(market&&Array.isArray(market.rows)){STATE.data.market=market;}renderAll();
}

rvHydrateSupplemental();
$('#refreshBtn')?.addEventListener('click',()=>setTimeout(rvHydrateSupplemental,500));
