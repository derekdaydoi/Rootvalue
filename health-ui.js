// Rootvalue data-health presentation layer.
(() => {
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
