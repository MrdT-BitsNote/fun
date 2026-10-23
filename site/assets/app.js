(function(){
"use strict";
var nav=document.querySelector('.nav'),bar=document.querySelector('.scroll-progress');
var heroIn=document.querySelector('.hero-in');
function onScroll(){
  var y=window.scrollY||document.documentElement.scrollTop;
  if(nav)nav.classList.toggle('show',y>640);
  if(bar){var h=document.documentElement.scrollHeight-window.innerHeight;
    bar.style.width=(h>0?(y/h*100):0)+'%';}
  if(heroIn&&y<window.innerHeight*1.2){
    var p=Math.min(y/(window.innerHeight*.85),1);
    heroIn.style.transform='translateY('+(y*.32)+'px) scale('+(1-p*.14)+')';
    heroIn.style.opacity=String(1-p*.9);
  }
}
window.addEventListener('scroll',onScroll,{passive:true});onScroll();

/* 进场动画 */
var io=('IntersectionObserver'in window)?new IntersectionObserver(function(es){
  es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target);}});
},{threshold:.08,rootMargin:'0px 0px -30px 0px'}):null;
document.querySelectorAll('.reveal').forEach(function(el){io?io.observe(el):el.classList.add('in');});

/* 数字滚动 */
function countUp(el){
  var target=parseFloat(el.getAttribute('data-count'))||0,dec=+(el.getAttribute('data-dec')||0);
  var t0=performance.now(),dur=1400;
  function step(t){
    var p=Math.min((t-t0)/dur,1),e=1-Math.pow(1-p,3);
    var v=target*e;
    el.textContent=dec?v.toFixed(dec):Math.round(v).toLocaleString('zh-CN');
    if(p<1)requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
var cio=('IntersectionObserver'in window)?new IntersectionObserver(function(es){
  es.forEach(function(e){if(e.isIntersecting){countUp(e.target);cio.unobserve(e.target);}});
},{threshold:.4}):null;
document.querySelectorAll('[data-count]').forEach(function(el){cio?cio.observe(el):
  el.textContent=(+(el.getAttribute('data-dec')||0)?(+el.getAttribute('data-count')).toFixed(+(el.getAttribute('data-dec')||0)):(+el.getAttribute('data-count')).toLocaleString('zh-CN'));});

/* 城市搜索 + 省筛选 */
var grid=document.getElementById('city-grid'),q=document.getElementById('city-q'),
    chips=document.getElementById('prov-chips'),cnt=document.getElementById('city-count');
var CITIES=[];try{CITIES=JSON.parse(document.getElementById('cities-data').textContent);}catch(e){}
var curProv='全部';
function renderCities(){
  if(!grid)return;
  var kw=(q&&q.value||'').trim().toLowerCase(),n=0,frag=document.createDocumentFragment();
  CITIES.forEach(function(c){
    var okP=curProv==='全部'||c.province===curProv;
    var okK=!kw||c.city.toLowerCase().indexOf(kw)>=0||c.province.toLowerCase().indexOf(kw)>=0;
    if(!okP||!okK)return;n++;
    var el=document.createElement('a');
    el.className='city-card';el.href=c.page;
    var gd='';
    ['S','A','B','C'].forEach(function(g){var v=c.grades[g]||0;
      if(v>0)gd+='<i class="g-'+g.toLowerCase()+'" style="width:'+(v/Math.max(c.districts||1,1)*100)+'%" title="'+g+'级 '+v+' 个"></i>';});
    el.innerHTML='<div class="cc-top"><span class="cc-name">'+esc(c.city)+'</span><span class="cc-prov">'+esc(c.province)+'</span></div>'
      +'<div class="cc-poi"><b>'+(c.poi||0).toLocaleString('zh-CN')+'</b> POI · 商圈 <b>'+(c.districts||0)+'</b> 处</div>'
      +'<div class="gradebar">'+gd+'</div>'
      +'<div class="cc-dims">'
      +dim(c.dims.food,'美食')+dim(c.dims.district,'商圈')+dim(c.dims.leisure,'休闲')
      +dim(c.dims.kids,'儿童')+dim(c.dims.hotel,'酒店')+dim(c.dims.product,'特产')
      +'</div><div class="cc-foot"><span class="cc-go">进入城市</span></div>';
    frag.appendChild(el);
  });
  grid.innerHTML='';
  if(n===0){grid.innerHTML='<div class="empty-hint">没有匹配的城市，换个关键词试试</div>';}
  else grid.appendChild(frag);
  if(cnt)cnt.textContent=n;
  function dim(v,l){return v>0?'<span class="dim-tag">'+l+' '+v+'</span>':'';}
}
function esc(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML;}
if(q)q.addEventListener('input',renderCities);
if(chips)chips.addEventListener('click',function(e){
  var b=e.target.closest('.chip');if(!b)return;
  chips.querySelectorAll('.chip').forEach(function(x){x.classList.remove('on');});
  b.classList.add('on');curProv=b.getAttribute('data-prov');renderCities();
});
/* 随机城市 */
var dice=document.getElementById('dice');
if(dice)dice.addEventListener('click',function(){
  var c=CITIES[Math.floor(Math.random()*CITIES.length)];
  if(c)location.href=c.page;
});
/* "/" 聚焦搜索 */
document.addEventListener('keydown',function(e){
  if(e.key==='/'&&document.activeElement!==q){e.preventDefault();if(q)q.focus();}
});

/* 商圈评级筛选 */
var dgrid=document.getElementById('dist-grid'),dchips=document.getElementById('dist-chips');
if(dgrid){
  var DTOP=[];try{DTOP=JSON.parse(document.getElementById('dist-data').textContent);}catch(e){}
  var curG='SA';
  function renderTop(){
    var frag=document.createDocumentFragment(),n=0;
    DTOP.forEach(function(d){
      if(curG.indexOf(d.grade)<0)return;n++;if(n>48)return;
      var el=document.createElement('a');el.className='dist-card';el.href=d.city_page;
      el.innerHTML='<div class="dc-head"><span class="grade-badge gb-'+d.grade.toLowerCase()+'">'+d.grade+'</span>'
        +'<span class="dc-name">'+esc(d.name)+'</span></div>'
        +'<div class="dc-meta">'+esc(d.carrier)+' · 评分 <b>'+(d.rating!=null?d.rating:'—')+'</b></div>'
        +'<div class="dc-counts"><span class="cnt">美食 <b>'+(d.food||0)+'</b></span>'
        +'<span class="cnt">休闲 <b>'+(d.leisure||0)+'</b></span>'
        +'<span class="cnt">儿童 <b>'+(d.kids||0)+'</b></span>'
        +'<span class="cnt">酒店 <b>'+(d.hotel||0)+'</b></span></div>'
        +'<div class="dc-city">'+esc(d.city)+' · '+esc(d.province)+'</div>';
      frag.appendChild(el);
    });
    dgrid.innerHTML='';dgrid.appendChild(frag);
  }
  if(dchips)dchips.addEventListener('click',function(e){
    var b=e.target.closest('.chip');if(!b)return;
    dchips.querySelectorAll('.chip').forEach(function(x){x.classList.remove('on');});
    b.classList.add('on');curG=b.getAttribute('data-g');renderTop();
  });
  renderTop();
}

/* 城市页：图片失败降级 + 复制链接 + 锚点高亮 */
document.querySelectorAll('.food-img img').forEach(function(img){
  img.addEventListener('error',function(){img.style.display='none';});
});
document.querySelectorAll('[data-copy]').forEach(function(btn){
  btn.addEventListener('click',function(){
    var txt=btn.getAttribute('data-copy');
    function done(){btn.textContent='已复制';setTimeout(function(){btn.textContent='复制';},1600);}
    if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(txt).then(done,done);}
    else{var ta=document.createElement('textarea');ta.value=txt;document.body.appendChild(ta);
      ta.select();try{document.execCommand('copy');}catch(e){}document.body.removeChild(ta);done();}
  });
});
var anchors=document.querySelectorAll('.anchor-nav a'),secs=[];
anchors.forEach(function(a){var s=document.querySelector(a.getAttribute('href'));if(s)secs.push([a,s]);});
if(secs.length){
  var aio=new IntersectionObserver(function(es){
    es.forEach(function(e){if(e.isIntersecting){
      anchors.forEach(function(a){a.classList.remove('on');});
      for(var i=0;i<secs.length;i++)if(secs[i][1]===e.target){secs[i][0].classList.add('on');break;}
    }});
  },{rootMargin:'-30% 0px -60% 0px'});
  secs.forEach(function(p){aio.observe(p[1]);});
}
/* 城市页商圈等级筛选 */
var cgrid=document.getElementById('city-dist-grid');
if(cgrid){
  var cchips=document.getElementById('city-dist-chips');
  function filt(g){
    cgrid.querySelectorAll('[data-g]').forEach(function(el){
      el.style.display=(g==='all'||el.getAttribute('data-g')===g)?'':'none';});
  }
  if(cchips)cchips.addEventListener('click',function(e){
    var b=e.target.closest('.chip');if(!b)return;
    cchips.querySelectorAll('.chip').forEach(function(x){x.classList.remove('on');});
    b.classList.add('on');filt(b.getAttribute('data-g'));
  });
}
})();