// Rootvalue data-health presentation layer.
(() => {
  const style=document.createElement('style');
  style.textContent=`
    [data-screen="data"] #sourceCards{margin-bottom:26px}
    [data-screen="data"] #sourceCards + .panel{margin-top:0}
    [data-screen="data"] .panel{margin-bottom:18px}
    .health-list{gap:0!important}
    .health-item-v2{display:grid!important;grid-template-columns:92px minmax(0,1fr);gap:16px!important;align-items:start!important;padding:15px 0!important;border-bottom:1px solid var(--line)!important;color:var(--ink)!important}
    .health-item-v2:last-child{border-bottom:0!important}
    .health-badge{display:inline-flex;align-items:center;justify-content:center;width:max-content;min-width:78px;padding:5px 8px;border-radius:999px;font-size:9px;font-weight:750;letter-spacing:.45px;background:var(--warning-soft);color:var(--warning)}
    .health-item-v2.error .health-badge{background:var(--danger-soft);color:var(--danger)}
    .health-item-v2.ok .health-badge{background:var(--brand-soft);color:var(--brand)}
    .health-copy{min-width:0}
    .health-copy strong{display:block;font-size:12px;font-weight:650;margin:0 0 4px;color:var(--ink)}
    .health-copy span{display:block;font-size:11px;line-height:1.55;color:var(--muted);overflow-wrap:anywhere}
    @media(max-width:760px){
      [data-screen="data"] #sourceCards{margin-bottom:20px}
      .health-item-v2{grid-template-columns:1fr;gap:7px!important;padding:14px 0!important}
      .health-badge{min-width:0}
      .health-copy strong{font-size:13px}.health-copy span{font-size:12px}
    }
  `;
  document.head.appendChild(style);

  const txt=(vi,en)=>STATE.lang==='vi'?vi:en;
  const esc=(v)=>escapeHtml(v);

  function parseHealth(health={}){
    const errors=(health.errors||[]).map(raw=>({kind:'error',title:txt('Lỗi pipeline','Pipeline error'),detail:String(raw)}));
    const warnings=(health.warnings||[]).map(String);
    const items=[];

    const api=warnings.find(x=>/VNSTOCK_API_KEY/i.test(x));
    if(api){
      items.push({
        kind:'warning',
        title:txt('Quyền truy cập BCTC','Financial-data access'),
        detail:txt('Chưa cấu hình VNSTOCK_API_KEY; nguồn guest hiện chỉ trả khoảng 4/8 kỳ năm. Đây là giới hạn độ phủ dữ liệu, không phải lỗi tính toán.','VNSTOCK_API_KEY is not configured; guest access currently returns about 4/8 annual periods. This is a coverage limitation, not a calculation failure.')
      });
    }

    const sbv=warnings.find(x=>/SBV historical state layer/i.test(x));
    if(sbv){
      const rawMissing=(sbv.split(':').slice(1).join(':')||'').split(',').map(x=>x.trim()).filter(Boolean);
      const labels={interbank_rate:txt('liên ngân hàng','interbank'),policy_rate:txt('lãi suất điều hành','policy rate'),omo:'OMO',credit:txt('tín dụng','credit'),money_supply:'M2',cpi:'CPI',exchange_rate:txt('tỷ giá','FX')};
      const missing=rawMissing.map(x=>labels[x]||x).join(' · ');
      items.push({
        kind:'warning',
        title:txt('Lịch sử trạng thái NHNN','SBV historical state'),
        detail:`${txt('Chưa đủ chuỗi lịch sử để chạy reaction model','Historical series are still incomplete for the reaction model')}${missing?`: ${missing}`:''}.`
      });
    }

    const coverage=warnings.map(x=>x.match(/^([A-Z0-9]+):\s*annual history\s*(\d+)\/(\d+)/i)).filter(Boolean);
    if(coverage.length){
      const byCoverage=new Map();
      coverage.forEach(m=>{const key=`${m[2]}/${m[3]}`;if(!byCoverage.has(key))byCoverage.set(key,[]);byCoverage.get(key).push(m[1]);});
      const detail=[...byCoverage.entries()].map(([cov,tickers])=>`${tickers.join(', ')}: ${cov} ${txt('năm','years')}`).join(' · ');
      items.push({
        kind:'warning',
        title:txt('Độ phủ BCTC','Financial-history coverage'),
        detail:`${detail}. ${txt('Mục tiêu Rootvalue là tối thiểu 8 năm cho mỗi doanh nghiệp.','Rootvalue requires at least 8 annual periods per company.')}`
      });
    }

    const consumed=x=>/VNSTOCK_API_KEY|SBV historical state layer|^[A-Z0-9]+:\s*annual history/i.test(x);
    warnings.filter(x=>!consumed(x)).forEach(raw=>items.push({kind:'warning',title:txt('Cảnh báo dữ liệu','Data warning'),detail:raw}));
    return [...errors,...items];
  }

  function healthMarkup(item){
    const label=item.kind==='error'?txt('LỖI','ERROR'):txt('CẢNH BÁO','WARNING');
    return `<div class="health-item health-item-v2 ${item.kind}"><span class="health-badge">${label}</span><div class="health-copy"><strong>${esc(item.title)}</strong><span>${esc(item.detail)}</span></div></div>`;
  }

  const baseRenderData=renderData;
  renderData=function(){
    baseRenderData();
    const root=$('#healthList');
    if(!root||!STATE.data)return;
    const items=parseHealth(STATE.data.health||{});
    root.innerHTML=items.length?items.map(healthMarkup).join(''):`<div class="health-item health-item-v2 ok"><span class="health-badge">OK</span><div class="health-copy"><strong>${txt('Không có lỗi dữ liệu','No data issues')}</strong><span>${txt('Các kiểm tra hiện tại không ghi nhận lỗi hoặc cảnh báo.','Current checks report no errors or warnings.')}</span></div></div>`;
  };

  if(STATE.data)renderData();
})();
