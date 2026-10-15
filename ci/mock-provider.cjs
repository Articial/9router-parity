'use strict';
// Synthetic server only. No HTTP client, fetch, proxy, shell or filesystem writes.
const http = require('node:http');
const KEY = 'gate-b-fake-provider-key';
const CONTROL = 'gate-b-fake-control-key';
const MAX_BODY = 524288, MAX_REQUESTS = 128;
const SCENARIOS = new Set(['ok','tools','slow-stream','long','rate-limit','unavailable','retry-503','timeout','stream-stall']);
let trace = [], counters = new Map(), total = 0;
const json = (res,status,value,headers={}) => {
  res.writeHead(status,{'content-type':'application/json',...headers});res.end(JSON.stringify(value));
};
const server = http.createServer(async (req,res) => {
  try {
    const path = req.url.split('?')[0];
    if (req.method==='GET' && path==='/health') return json(res,200,{ok:true});
    if (path==='/__trace' || path==='/__reset') {
      if (req.headers['x-gate-b-control']!==CONTROL) return json(res,403,{error:'control-denied'});
      if (req.method==='GET' && path==='/__trace') return json(res,200,{trace,total});
      if (req.method==='POST' && path==='/__reset') {
        trace=[];counters=new Map();return json(res,200,{ok:true});
      }
      return json(res,405,{error:'method'});
    }
    const match=path.match(/^\/(a|b|r)\/v1\/(chat\/completions|responses)$/);
    if (req.method!=='POST' || !match) return json(res,404,{error:'path'});
    if (req.headers.authorization!=='Bearer '+KEY) return json(res,401,{error:{message:'fake-key-required',type:'authentication_error'}});
    if (++total>MAX_REQUESTS) return json(res,429,{error:{message:'mock-run-budget-exhausted'}});
    let size=0, chunks=[];
    for await (const chunk of req) {
      size+=chunk.length;
      if (size>MAX_BODY) {json(res,413,{error:'body-limit'});req.destroy();return;}
      chunks.push(chunk);
    }
    const body=JSON.parse(Buffer.concat(chunks).toString('utf8'));
    const model=body.model, lane=match[1], responses=match[2]==='responses';
    if (!SCENARIOS.has(model)) return json(res,400,{error:{message:'scenario-not-allowed'}});
    const attempt=(counters.get(lane+'/'+model)||0)+1;counters.set(lane+'/'+model,attempt);
    const row={lane,scenario:model,attempt,format:responses?'responses':'chat',stream:body.stream===true,status:200,cancelled:false};
    trace.push(row);
    res.on('close',()=>{if(!res.writableEnded) row.cancelled=true;});
    if (model==='rate-limit' || model==='unavailable' || (model==='retry-503' && attempt===1)) {
      row.status=model==='rate-limit'?429:503;
      return json(res,row.status,{error:{message:'synthetic-'+row.status,type:row.status===429?'rate_limit_error':'server_error'}},{'retry-after':'1'});
    }
    if(model==='timeout') {
      const timer=setTimeout(()=>{if(!res.destroyed)json(res,200,{error:'unexpected-timeout-completion'});},10000);
      res.on('close',()=>clearTimeout(timer));return;
    }
    const material=JSON.stringify(body.messages||body.input||[]);
    const toolReturn=material.includes('function_call_output') || (Array.isArray(body.messages)&&body.messages.some(x=>x.role==='tool'));
    const text=model==='long' ? (['GB_START_7','GB_MIDDLE_7','GB_END_7'].every(x=>material.includes(x))?'LONG_MARKERS_OK':'LONG_MARKERS_MISSING') : toolReturn?'TOOL_ROUNDTRIP_OK':'MOCK_'+lane.toUpperCase()+'_OK';
    const args=JSON.stringify({nested:{value:7},label:'synthetic-é'});
    const tools=model==='tools' && !toolReturn;
    const call={id:'call_gate_b',type:'function',function:{name:'gate_b_echo',arguments:args}};
    const responseOutput=tools?[{id:'fc_gate_b',type:'function_call',call_id:'call_gate_b',name:'gate_b_echo',arguments:args,status:'completed'}]:[{id:'msg_gate_b',type:'message',role:'assistant',status:'completed',content:[{type:'output_text',text,annotations:[]}]}];
    const finalResponse={id:'resp_gate_b',object:'response',created_at:0,status:'completed',error:null,incomplete_details:null,model,output:responseOutput,usage:{input_tokens:10,output_tokens:5,total_tokens:15}};
    const finalChat={id:'chat_gate_b',object:'chat.completion',created:0,model,choices:[{index:0,message:{role:'assistant',content:tools?null:text,...(tools?{tool_calls:[call]}:{})},finish_reason:tools?'tool_calls':'stop'}],usage:{prompt_tokens:10,completion_tokens:5,total_tokens:15}};
    if(body.stream!==true) return json(res,200,responses?finalResponse:finalChat);
    res.writeHead(200,{'content-type':'text/event-stream','cache-control':'no-cache'});
    let seq=0;
    const event=(type,data)=>res.write('event: '+type+'\ndata: '+JSON.stringify({type,sequence_number:seq++,...data})+'\n\n');
    const chunk=(delta,finish=null)=>res.write('data: '+JSON.stringify({id:'chat_gate_b',object:'chat.completion.chunk',created:0,model,choices:[{index:0,delta,finish_reason:finish}]})+'\n\n');
    if(responses) {
      event('response.created',{response:{...finalResponse,status:'in_progress',output:[]}});
      event('response.output_item.added',{output_index:0,item:tools?{...responseOutput[0],arguments:'',status:'in_progress'}:{...responseOutput[0],content:[],status:'in_progress'}});
      if(!tools)event('response.content_part.added',{item_id:'msg_gate_b',output_index:0,content_index:0,part:{type:'output_text',text:'',annotations:[]}});
    } else chunk({role:'assistant',content:''});
    const pieces=tools?[args.slice(0,16),args.slice(16)]:[text.slice(0,5),text.slice(5)];
    if(model==='slow-stream')for(let i=0;i<20;i++)pieces.push(' synthetic');
    let index=0;
    const timer=setInterval(()=>{
      if(res.destroyed){clearInterval(timer);return;}
      if(model==='stream-stall' && index>0)return;
      if(index<pieces.length) {
        const delta=pieces[index];
        if(responses)event(tools?'response.function_call_arguments.delta':'response.output_text.delta',{item_id:tools?'fc_gate_b':'msg_gate_b',output_index:0,content_index:0,delta});
        else chunk(tools?{tool_calls:[{index:0,...(index===0?{id:'call_gate_b',type:'function'}:{}),function:{...(index===0?{name:'gate_b_echo'}:{}),arguments:delta}}]}:{content:delta});
        index++;return;
      }
      clearInterval(timer);
      if(responses) {
        event(tools?'response.function_call_arguments.done':'response.output_text.done',{item_id:tools?'fc_gate_b':'msg_gate_b',output_index:0,...(tools?{arguments:args}:{content_index:0,text})});
        if(!tools)event('response.content_part.done',{item_id:'msg_gate_b',output_index:0,content_index:0,part:responseOutput[0].content[0]});
        event('response.output_item.done',{output_index:0,item:responseOutput[0]});event('response.completed',{response:finalResponse});res.end();
      } else {chunk({},tools?'tool_calls':'stop');res.end('data: [DONE]\n\n');}
    },200);
    const bound=setTimeout(()=>res.destroy(),12000);
    res.on('close',()=>{clearInterval(timer);clearTimeout(bound);});
  } catch {if(!res.headersSent)json(res,400,{error:'synthetic-invalid-request'});else res.destroy();}
});
server.maxConnections=4;
server.requestTimeout=15000;server.headersTimeout=5000;
server.listen(18080,'0.0.0.0');
