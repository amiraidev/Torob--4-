export function comparePayment({cash,upfront=0,months=0,monthly=0,fees=0}){
  const values=[cash,upfront,months,monthly,fees];
  if(values.some(v=>!Number.isSafeInteger(v)||v<0)||cash<=0||months<1||months>120)return {error:'مبالغ را به تومان و تعداد اقساط را بین ۱ تا ۱۲۰ وارد کن.'};
  const total=upfront+months*monthly+fees;
  if(!Number.isSafeInteger(total)||total<=0)return {error:'مجموع پرداخت معتبر نیست.'};
  return {total,difference:total-cash,markupPercent:Math.round((total-cash)/cash*10000)/100};
}
