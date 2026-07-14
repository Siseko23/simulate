(function(){
  const CITY_COORDS = {
    'durban': {lat:-29.8587,lng:31.0218,label:'Durban, KZN', query:'Durban, KwaZulu-Natal, South Africa'},
    'durban, kzn': {lat:-29.8587,lng:31.0218,label:'Durban, KZN', query:'Durban, KwaZulu-Natal, South Africa'},
    'johannesburg': {lat:-26.2041,lng:28.0473,label:'Johannesburg, GP', query:'Johannesburg, Gauteng, South Africa'},
    'johannesburg, gp': {lat:-26.2041,lng:28.0473,label:'Johannesburg, GP', query:'Johannesburg, Gauteng, South Africa'},
    'pretoria': {lat:-25.7479,lng:28.2293,label:'Pretoria, GP', query:'Pretoria, Gauteng, South Africa'},
    'cape town': {lat:-33.9249,lng:18.4241,label:'Cape Town, WC', query:'Cape Town, Western Cape, South Africa'},
    'gqeberha': {lat:-33.9608,lng:25.6022,label:'Gqeberha, EC', query:'Gqeberha, Eastern Cape, South Africa'},
    'port elizabeth': {lat:-33.9608,lng:25.6022,label:'Gqeberha, EC', query:'Gqeberha, Eastern Cape, South Africa'},
    'bloemfontein': {lat:-29.0852,lng:26.1596,label:'Bloemfontein, FS', query:'Bloemfontein, Free State, South Africa'},
    'pietermaritzburg': {lat:-29.6006,lng:30.3794,label:'Pietermaritzburg, KZN', query:'Pietermaritzburg, KwaZulu-Natal, South Africa'},
    'ladysmith': {lat:-28.5597,lng:29.7808,label:'Ladysmith, KZN', query:'Ladysmith, KwaZulu-Natal, South Africa'},
    'harrismith': {lat:-28.2728,lng:29.1295,label:'Harrismith, FS', query:'Harrismith, Free State, South Africa'},
    'richards bay': {lat:-28.7807,lng:32.0383,label:'Richards Bay, KZN', query:'Richards Bay, KwaZulu-Natal, South Africa'},
    'nelspruit': {lat:-25.4753,lng:30.9694,label:'Mbombela, MP', query:'Mbombela, Mpumalanga, South Africa'},
    'mbombela': {lat:-25.4753,lng:30.9694,label:'Mbombela, MP', query:'Mbombela, Mpumalanga, South Africa'}
  };

  const LIGHT_ROAD_STYLE = [
    {elementType:'geometry',stylers:[{color:'#f8fafc'}]},
    {elementType:'labels.text.fill',stylers:[{color:'#475569'}]},
    {elementType:'labels.text.stroke',stylers:[{color:'#ffffff'},{weight:3}]},
    {featureType:'administrative.country',elementType:'geometry.stroke',stylers:[{color:'#cbd5e1'}]},
    {featureType:'administrative.province',elementType:'geometry.stroke',stylers:[{color:'#e2e8f0'}]},
    {featureType:'landscape',elementType:'geometry',stylers:[{color:'#f8fafc'}]},
    {featureType:'poi',stylers:[{visibility:'off'}]},
    {featureType:'road',elementType:'geometry',stylers:[{color:'#e2e8f0'}]},
    {featureType:'road',elementType:'labels.icon',stylers:[{visibility:'off'}]},
    {featureType:'road.highway',elementType:'geometry',stylers:[{color:'#fde68a'}]},
    {featureType:'road.highway',elementType:'labels.text.fill',stylers:[{color:'#334155'}]},
    {featureType:'transit',stylers:[{visibility:'off'}]},
    {featureType:'water',elementType:'geometry',stylers:[{color:'#dbeafe'}]},
    {featureType:'water',elementType:'labels.text.fill',stylers:[{color:'#64748b'}]}
  ];

  function resolve(value, fallback){
    if(!value) return fallback;
    const clean = String(value).toLowerCase().replace(/\s+/g,' ').trim();
    for(const key of Object.keys(CITY_COORDS)){
      if(clean.includes(key)) return CITY_COORDS[key];
    }
    return {...fallback, label:String(value), query:String(value)};
  }

  function truckSvg(){
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="44" viewBox="0 0 64 44"><defs><filter id="s" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="5" stdDeviation="4" flood-color="#0f172a" flood-opacity=".32"/></filter></defs><g filter="url(#s)"><rect x="6" y="11" width="35" height="18" rx="3" fill="#fff" stroke="#0f172a" stroke-width="1.4"/><path d="M41 16h9l7 7v6H41z" fill="#fff" stroke="#0f172a" stroke-width="1.4"/><rect x="45" y="18" width="5" height="4" rx="1" fill="#0f172a"/><circle cx="17" cy="31" r="5" fill="#0f172a"/><circle cx="47" cy="31" r="5" fill="#0f172a"/><circle cx="17" cy="31" r="2" fill="#fff"/><circle cx="47" cy="31" r="2" fill="#fff"/><rect x="10" y="15" width="25" height="3" rx="1.5" fill="#ef233c"/></g></svg>`;
    return {url:'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(svg), scaledSize:new google.maps.Size(64,44), anchor:new google.maps.Point(32,33)};
  }

  function buildFallback(el){
    if(el.querySelector('.ffn-map-fallback')) return;
    const shell = el.closest('.ffn-sa-map-shell') || el;
    const status = shell.dataset.status || el.dataset.status || 'In Transit';
    const summary = shell.dataset.summary || el.dataset.summary || 'Johannesburg to Durban via the N3 corridor';
    el.innerHTML = `<div class="ffn-map-fallback"><div class="ffn-map-country"></div><div class="ffn-map-route"></div><span class="ffn-map-pin origin"></span><span class="ffn-map-pin current"></span><span class="ffn-map-pin dest"></span><span class="ffn-map-city origin">Johannesburg</span><span class="ffn-map-city current">Pietermaritzburg</span><span class="ffn-map-city dest">Durban</span><div class="ffn-map-truck"></div></div><div class="ffn-map-controls"><span class="ffn-map-chip live">Fallback route</span><span class="ffn-map-chip">Add Google Maps key</span></div><div class="ffn-map-overlay"><strong>${status}</strong><p>${summary}</p></div><div class="ffn-map-error"></div>`;
  }

  function addOverlay(shell, status, summary){
    shell.querySelectorAll(':scope > .ffn-map-overlay, :scope > .ffn-map-controls').forEach(n => n.remove());
    const overlay=document.createElement('div');
    overlay.className='ffn-map-overlay';
    overlay.innerHTML=`<strong>${status}</strong><p>${summary}</p>`;
    shell.appendChild(overlay);
    const controls=document.createElement('div');
    controls.className='ffn-map-controls';
    controls.innerHTML='<span class="ffn-map-chip live">Google route</span><span class="ffn-map-chip">Road map</span>';
    shell.appendChild(controls);
  }

  function toLiteral(latLng){ return {lat:latLng.lat(), lng:latLng.lng()}; }
  function dist(a,b){
    const R=6371e3, p1=a.lat*Math.PI/180, p2=b.lat*Math.PI/180;
    const dp=(b.lat-a.lat)*Math.PI/180, dl=(b.lng-a.lng)*Math.PI/180;
    const x=Math.sin(dp/2)**2 + Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
    return 2*R*Math.atan2(Math.sqrt(x), Math.sqrt(1-x));
  }
  function interpolate(a,b,t){ return {lat:a.lat+(b.lat-a.lat)*t, lng:a.lng+(b.lng-a.lng)*t}; }
  function splitPathAtProgress(pathLatLng, progress){
    const path = pathLatLng.map(toLiteral);
    if(path.length < 2) return {travelled:path, remaining:path, point:path[0] || null};
    const segments=[]; let total=0;
    for(let i=0;i<path.length-1;i++){ const d=dist(path[i],path[i+1]); segments.push(d); total+=d; }
    const target=Math.max(0,Math.min(1,progress))*total;
    let acc=0;
    for(let i=0;i<segments.length;i++){
      if(acc + segments[i] >= target){
        const t=(target-acc)/(segments[i]||1);
        const point=interpolate(path[i],path[i+1],t);
        return {travelled:[...path.slice(0,i+1), point], remaining:[point, ...path.slice(i+1)], point};
      }
      acc += segments[i];
    }
    const point=path[path.length-1];
    return {travelled:path, remaining:[point], point};
  }
  function fitPath(map,path){
    const bounds=new google.maps.LatLngBounds();
    path.forEach(p=>bounds.extend(p));
    map.fitBounds(bounds, {top:48,right:48,bottom:48,left:48});
  }

  function routeMap(shell){
    const mapEl = shell.querySelector('.ffn-sa-map');
    if(!mapEl) return;
    if(!(window.google && google.maps)) { buildFallback(mapEl); return; }

    const origin = resolve(shell.dataset.origin || mapEl.dataset.origin, CITY_COORDS['johannesburg']);
    const destination = resolve(shell.dataset.destination || mapEl.dataset.destination, CITY_COORDS['durban']);
    const current = resolve(shell.dataset.current || mapEl.dataset.current, CITY_COORDS['pietermaritzburg']);
    const status = shell.dataset.status || mapEl.dataset.status || 'In Transit';
    const summary = shell.dataset.summary || mapEl.dataset.summary || `${origin.label} to ${destination.label}`;
    const progress = Number(shell.dataset.progress || mapEl.dataset.progress || 0.72);

    mapEl.innerHTML = '';
    const map = new google.maps.Map(mapEl, {
      center: current,
      zoom: 6,
      mapTypeId: google.maps.MapTypeId.ROADMAP,
      styles: LIGHT_ROAD_STYLE,
      mapTypeControl: false,
      streetViewControl: false,
      fullscreenControl: true,
      zoomControl: true,
      restriction:{latLngBounds:{north:-21.5,south:-35.5,west:16.0,east:33.8}, strictBounds:false}
    });

    const directionsService = new google.maps.DirectionsService();
    directionsService.route({
      origin: origin.query || origin,
      destination: destination.query || destination,
      travelMode: google.maps.TravelMode.DRIVING,
      drivingOptions: {departureTime: new Date(), trafficModel: google.maps.TrafficModel.BEST_GUESS},
      provideRouteAlternatives:false
    }, (result, state) => {
      if(state === 'OK' && result.routes && result.routes[0]) {
        const path = result.routes[0].overview_path;
        const split = splitPathAtProgress(path, progress);
        const glowBase = {map, strokeOpacity:.16, strokeWeight:13, clickable:false, zIndex:1};
        new google.maps.Polyline({...glowBase, path:split.travelled, strokeColor:'#16a34a'});
        new google.maps.Polyline({...glowBase, path:split.remaining, strokeColor:'#ef233c'});
        new google.maps.Polyline({map,path:split.travelled,strokeColor:'#16a34a',strokeOpacity:1,strokeWeight:5,clickable:false,zIndex:2});
        new google.maps.Polyline({map,path:split.remaining,strokeColor:'#f59e0b',strokeOpacity:1,strokeWeight:5,clickable:false,zIndex:2});
        const lastLeg = result.routes[0].legs && result.routes[0].legs[result.routes[0].legs.length-1];
        fitPath(map, path);
        new google.maps.Marker({position:origin,map,title:origin.label,icon:{path:google.maps.SymbolPath.CIRCLE,scale:8,fillColor:'#16a34a',fillOpacity:1,strokeColor:'#fff',strokeWeight:3}});
        new google.maps.Marker({position:destination,map,title:destination.label,icon:{path:google.maps.SymbolPath.CIRCLE,scale:8,fillColor:'#ef233c',fillOpacity:1,strokeColor:'#fff',strokeWeight:3}});
        const truckMarker = new google.maps.Marker({position:split.point,map,title:'Live truck position',icon:truckSvg(),zIndex:10});
        const summaryText = lastLeg ? `${origin.label} to ${destination.label} - ${lastLeg.distance.text}, ${lastLeg.duration.text}` : summary;
        addOverlay(shell, status, summaryText);
        const info = new google.maps.InfoWindow({content:'<div style="color:#0f172a;font-weight:800">Live truck</div><div style="color:#475569">Driver is on route to Durban</div>'});
        if(shell.dataset.openInfo === 'true') info.open({map, anchor:truckMarker});
      } else {
        new google.maps.Polyline({map,path:[origin,current,destination],strokeColor:'#ef233c',strokeWeight:5,strokeOpacity:.95});
        new google.maps.Marker({position:origin,map,title:origin.label});
        new google.maps.Marker({position:destination,map,title:destination.label});
        new google.maps.Marker({position:current,map,title:'Live truck position',icon:truckSvg(),zIndex:10});
        const err=shell.querySelector('.ffn-map-error');
        if(err){err.style.display='block';err.textContent='Google route unavailable; showing fallback line';}
        addOverlay(shell, status, summary);
      }
    });
  }

  window.initFfnSaMaps = function(){
    document.querySelectorAll('.ffn-sa-map-shell').forEach(routeMap);
  };

  document.addEventListener('DOMContentLoaded', () => {
    if(window.google && google.maps) window.initFfnSaMaps();
    else setTimeout(() => {
      if(!(window.google && google.maps)) document.querySelectorAll('.ffn-sa-map').forEach(buildFallback);
    }, 1200);
  });
})();
