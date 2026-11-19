(function(){
  const box=document.querySelector('[data-assistant]'); if(!box) return;
  const toggle=box.querySelector('.assistant-toggle'), form=box.querySelector('.assistant-form'), input=box.querySelector('input'), messages=box.querySelector('.assistant-messages');
  function add(text,who){const el=document.createElement('div');el.className='bubble '+(who==='me'?'me':'bot');el.textContent=text;messages.appendChild(el);messages.scrollTop=messages.scrollHeight;}
  toggle.addEventListener('click',()=>{box.classList.toggle('open'); if(box.classList.contains('open')) input.focus();});
  form.addEventListener('submit',async e=>{e.preventDefault();const text=input.value.trim();if(!text)return;add(text,'me');input.value='';
    try{const r=await fetch(form.dataset.url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':form.dataset.csrf},body:JSON.stringify({message:text})});const data=await r.json();add(data.message,'bot');if(data.action){setTimeout(()=>{const map={deposit:'/transactions/deposit/',withdraw:'/transactions/withdraw/',transactions:'/transactions/report/'};if(map[data.action]) window.location.href=map[data.action]},500)}}catch(err){add('I could not process that request. Please try again.','bot')}
  });
})();
