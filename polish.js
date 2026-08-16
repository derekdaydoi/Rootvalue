// Final localization pass for Rootvalue analysis surfaces.
Object.assign(I18N.vi,{
  'missing.interbank_rate':'Lãi suất liên ngân hàng',
  'missing.policy_rate':'Lãi suất điều hành',
  'missing.omo':'Nghiệp vụ thị trường mở',
  'missing.credit':'Tăng trưởng tín dụng',
  'missing.money_supply':'Cung tiền M2',
  'missing.cpi':'CPI',
  'missing.exchange_rate':'Tỷ giá NHNN'
});
Object.assign(I18N.en,{
  'missing.interbank_rate':'Interbank rates',
  'missing.policy_rate':'Policy rates',
  'missing.omo':'Open-market operations',
  'missing.credit':'Credit growth',
  'missing.money_supply':'M2 money supply',
  'missing.cpi':'CPI',
  'missing.exchange_rate':'SBV exchange rate'
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

if(STATE.data)renderAll();
