
(function(){
  var box=document.getElementById('q');
  if(!box)return;
  var cards=[].slice.call(document.querySelectorAll('[data-name]'));
  var chips=[].slice.call(document.querySelectorAll('.filters button'));
  var filt='all';
  box.addEventListener('input',function(){
    var v=box.value.trim().toLowerCase();
    cards.forEach(function(c){
      var hit=!v||c.getAttribute('data-name').toLowerCase().indexOf(v)>=0
        ||c.getAttribute('data-prov').toLowerCase().indexOf(v)>=0;
      var f=filt==='all'||c.getAttribute('data-dim')===filt;
      c.style.display=(hit&&f)?'':'none';
    });
  });
  chips.forEach(function(b){
    b.addEventListener('click',function(){
      chips.forEach(function(x){x.classList.remove('on')});
      b.classList.add('on');filt=b.getAttribute('data-f');
      box.dispatchEvent(new Event('input'));
    });
  });
})();
