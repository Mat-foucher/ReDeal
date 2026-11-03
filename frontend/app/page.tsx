'use client';
import {useCallback, useEffect, useState} from 'react';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const usd = (cents:number) => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(cents/100);
type Subscription = {id:number;provider:string;plan_name:string;monthly_cost_cents:number};
type ScoutDeal = {id:number;provider:string;plan_name:string;current_plan:string;current_monthly_cents:number;target_monthly_cents:number;annual_savings_cents:number;billing_period:string;upfront_cents:number;eligibility:string;tradeoffs:string;source_url:string;status:string;caveat:string;review_reason:string};
type PayPalDeal = {id:string;provider:string;current_plan:string;target_plan:string;current_monthly_cents:number;target_monthly_cents:number;estimated_annual_savings_cents:number;caveat:string};
type PayPalPayload = {deals:PayPalDeal[];subscription:{current_plan:string;status:string};realized_savings_cents:number};

export default function Home(){
  const [tab,setTab] = useState<'pile'|'subscriptions'|'paypal'>('pile');
  const [subs,setSubs] = useState<Subscription[]>([]);
  const [pile,setPile] = useState<ScoutDeal[]>([]);
  const [provider,setProvider] = useState('Spotify');
  const [plan,setPlan] = useState('Premium');
  const [price,setPrice] = useState('15.99');
  const [loading,setLoading] = useState(false);
  const [message,setMessage] = useState('');
  const [paypal,setPaypal] = useState<PayPalPayload|null>(null);
  const [paypalError,setPaypalError] = useState('');
  const [actionKey,setActionKey] = useState('');

  const fetchJson = async (path:string, init?:RequestInit) => {
    const response = await fetch(`${API}${path}`, {cache:'no-store', ...init});
    const body = await response.json();
    if (!response.ok) throw new Error(typeof body.detail==='string' ? body.detail : JSON.stringify(body.detail || body));
    return body;
  };
  const reload = useCallback(async () => {
    try {
      const [s,p] = await Promise.all([
        fetch(`${API}/subscriptions`,{cache:'no-store'}).then(r=>r.json()),
        fetch(`${API}/agent/pile`,{cache:'no-store'}).then(r=>r.json())
      ]);
      if (Array.isArray(s)) setSubs(s);
      if (Array.isArray(p.deals)) setPile(p.deals);
    } catch(e) {setMessage(`Unable to load backend: ${String(e)}`);}
  }, []);
  useEffect(()=>{void reload();},[reload]);

  async function addSubscription(){
    try {
      const amount = Number(price);
      if (!provider.trim() || !plan.trim() || !Number.isFinite(amount) || amount<=0) throw new Error('Enter a provider, plan, and positive monthly price.');
      await fetchJson('/subscriptions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:provider.trim(),category:'digital',plan_name:plan.trim(),monthly_cost_cents:Math.round(amount*100),cancellation_fee_cents:0,status:'active'})});
      setMessage('Subscription saved. Click Scan for deals to start AI research.');
      await reload(); setTab('pile');
    } catch(e) {setMessage(String(e));}
  }
  async function scan(){
    setLoading(true);setMessage('AI Scout is researching and reviewing public offers. This can take a few minutes.');
    try {
      const result = await fetchJson('/agent/scan',{method:'POST'});
      setMessage(`Scout finished: ${result.new_deals} new offers, ${result.rejected} rejected. ${result.errors?.join(' | ') || ''}`);
      await reload();
    } catch(e) {setMessage(String(e));}
    finally {setLoading(false);}
  }
  async function swipe(id:number, decision:'approve'|'pass'){
    try {
      const result = await fetchJson(`/agent/pile/${id}/swipe`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision})});
      setMessage(result.message);await reload();
    } catch(e){setMessage(String(e));}
  }
  async function loadPaypal(){
    try {const result = await fetchJson('/demo/deals');setPaypal(result);setPaypalError('');}
    catch(e){setPaypalError(String(e));}
  }
  async function revisePaypal(dealId:string){
    if (!window.confirm('Request a real PayPal SANDBOX plan revision? This is separate from mock AI deals.')) return;
    try {
      const result = await fetchJson('/demo/revise',{method:'POST',headers:{'Content-Type':'application/json','X-Demo-Action-Key':actionKey},body:JSON.stringify({deal_id:dealId,approve:true})});
      setMessage(result.message || 'Sandbox revision requested.');
      if(result.approval_url){const u=new URL(result.approval_url);if(['www.sandbox.paypal.com','sandbox.paypal.com'].includes(u.hostname))window.location.assign(result.approval_url);}
    }catch(e){setMessage(String(e));}
  }
  return <main className="shell">
    <header><div><div className="brand">✦ ReDealer <span>AI Scout</span></div><p>Real research. Mock decisions. Better subscription choices.</p></div><div className="sandbox">PROTOTYPE</div></header>
    <nav>
      <button className={tab==='pile'?'active':''} onClick={()=>setTab('pile')}>♥ Swipe Pile ({pile.length})</button>
      <button className={tab==='subscriptions'?'active':''} onClick={()=>setTab('subscriptions')}>Subscriptions ({subs.length})</button>
      <button className={tab==='paypal'?'active':''} onClick={()=>{setTab('paypal');void loadPaypal();}}>PayPal Sandbox</button>
    </nav>
    {message && <div className="notice">{message}</div>}
    {tab==='pile' && <>
      <section className="hero"><div className="eyebrow">VERIFIED REALIZED SAVINGS</div><div className="amount">$0.00</div><p>Research and mock approvals do not count as realized savings.</p><button className="primary" disabled={loading||subs.length===0} onClick={()=>void scan()}>{loading?'Researching deals…':'⌕ Scan for deals with AI'}</button></section>
      {subs.length===0 && <section className="panel"><h2>Your Swipe Pile is waiting</h2><p>Add a subscription and its current monthly cost to let the Scout research alternatives.</p><button className="primary" onClick={()=>setTab('subscriptions')}>Add a subscription</button></section>}
      {subs.length>0 && pile.length===0 && <section className="panel"><h2>No offers in your pile yet</h2><p>Run a scan to search for publicly advertised subscription plans. The Scout may return no offers if prices or terms cannot be supported.</p></section>}
      <section className="pileGrid">{pile.map(d=><article className="dealCard" key={d.id}>
        <div className="eyebrow">AI-RESEARCHED · MOCK OFFER · {d.status==='conditional'?'CONDITIONAL':'REVIEW REQUIRED'}</div>
        <h2>{d.provider} — {d.plan_name}</h2><p className="muted">From {d.current_plan}</p>
        <div className="comparison"><div><small>CURRENT</small><strong>{usd(d.current_monthly_cents)}<em>/mo</em></strong></div><span>→</span><div><small>CANDIDATE</small><strong className="green">{usd(d.target_monthly_cents)}<em>/mo*</em></strong></div></div>
        <div className="saving">Potential savings: {usd(d.annual_savings_cents)}/year</div>
        {d.billing_period==='yearly' && <p>Annual upfront payment: {usd(d.upfront_cents)}. Monthly figure is an equivalent.</p>}
        <p><b>Eligibility:</b> {d.eligibility || 'Not established'}</p>
        <p><b>Tradeoffs:</b> {d.tradeoffs || 'Not established'}</p>
        <p className="muted">{d.caveat}</p>
        <p><a href={d.source_url} target="_blank" rel="noopener noreferrer">Review source and current terms</a></p>
        <div className="actions"><button className="pass" onClick={()=>void swipe(d.id,'pass')}>✕ Pass</button><button className="primary" onClick={()=>void swipe(d.id,'approve')}>♥ Mock approve</button></div>
      </article>)}</section>
    </>}
    {tab==='subscriptions' && <section className="panel"><div className="eyebrow">CURRENT SUBSCRIPTIONS</div><h2>Add a subscription</h2>
      <div className="formGrid"><label>Provider<input value={provider} onChange={e=>setProvider(e.target.value)} placeholder="Spotify" /></label><label>Plan<input value={plan} onChange={e=>setPlan(e.target.value)} placeholder="Premium" /></label><label>Monthly price (USD)<input type="number" min="0.01" step="0.01" value={price} onChange={e=>setPrice(e.target.value)}/></label></div>
      <button className="primary" onClick={()=>void addSubscription()}>Save subscription</button>
      <h2>Tracked subscriptions</h2>{subs.length===0?<p>Nothing tracked yet.</p>:subs.map(s=><p key={s.id}>{s.provider} — {s.plan_name} · {usd(s.monthly_cost_cents)}/month</p>)}
    </section>}
    {tab==='paypal' && <section className="panel"><div className="eyebrow">SEPARATE INTEGRATION · PAYPAL SANDBOX</div><h2>PayPal demo</h2><p>AI Scout mock approvals never call PayPal. This section retains the existing optional sandbox revision workflow.</p>
      {paypalError && <div className="notice">{paypalError}. Configure the PayPal variables in backend/.env to use this optional demo.</div>}
      {paypal && <><p>Sandbox plan: {paypal.subscription.current_plan} · {paypal.subscription.status}</p><p>Verified realized savings: {usd(paypal.realized_savings_cents)}</p>
        {paypal.deals.map(d=><article key={d.id}><h3>{d.provider}: {d.target_plan}</h3><p>Potential: {usd(d.estimated_annual_savings_cents)}/year</p><label>Demo action key<input type="password" value={actionKey} onChange={e=>setActionKey(e.target.value)}/></label><div className="actions"><button disabled={actionKey.length<16} onClick={()=>void revisePaypal(d.id)}>Request PayPal sandbox revision</button></div></article>)}
      </>}
    </section>}
    <footer>ReDealer prototype · AI-assisted research is not proof of price or eligibility · Mock swipes never purchase or cancel · API keys remain server-side</footer>
  </main>;
}
