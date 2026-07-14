(function(){
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/driver/service-worker.js').catch(function(){});
  }
  document.querySelectorAll('[data-gps-ref]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var ref = btn.getAttribute('data-gps-ref');
      var status = document.getElementById('driver-gps-status');
      function send(lat,lng){
        fetch('/driver/app/job/' + encodeURIComponent(ref) + '/location', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({lat:lat,lng:lng})
        }).then(function(r){return r.json();}).then(function(data){
          status.textContent = data.ok ? 'Location shared with FreightFlow.' : (data.error || 'Location failed.');
        }).catch(function(){ status.textContent='Location failed.'; });
      }
      if(navigator.geolocation){
        navigator.geolocation.getCurrentPosition(function(pos){ send(pos.coords.latitude,pos.coords.longitude); }, function(){ send(-29.6006,30.3794); });
      } else { send(-29.6006,30.3794); }
    });
  });
})();
