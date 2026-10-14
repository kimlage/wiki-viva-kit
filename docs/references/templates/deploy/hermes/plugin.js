import React from 'react';
import {ROUTES_AREA, SIDEBAR_NAV_AREA} from '@hermes/plugin-sdk';

// The installer replaces this synthetic loopback URL. No wiki data is bundled.
const boardURL = '__WIKI_BOARD_URL__';
function WikiBoard() {
  const [generation, setGeneration] = React.useState(0);
  return React.createElement('section', {style:{height:'100%',minHeight:'80vh',display:'flex',flexDirection:'column'}},
    React.createElement('header', {style:{display:'flex',gap:16,padding:'8px 16px',alignItems:'center'}},
      React.createElement('strong', null, 'Wiki Viva · Kanban'),
      React.createElement('a', {href:boardURL,target:'_blank',rel:'noopener noreferrer'}, 'Open wiki'),
      React.createElement('button', {onClick:()=>setGeneration(n=>n+1)}, 'Reload')),
    React.createElement('iframe', {
      key:generation,src:boardURL,title:'Wiki Viva action board',
      style:{border:0,width:'100%',flex:1,minHeight:'75vh'},
      referrerPolicy:'no-referrer',
      // Keep writes same-origin inside the wiki; no top-level navigation or downloads.
      sandbox:'allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox'
    }));
}
export default {
  id:'wiki-viva-board',name:'Wiki Viva Kanban',defaultEnabled:true,
  register(ctx) {
    ctx.registerMany([
      {id:'page',area:ROUTES_AREA,data:{path:'/wiki-board'},render:()=>React.createElement(WikiBoard)},
      {id:'nav',area:SIDEBAR_NAV_AREA,data:{path:'/wiki-board',label:'Wiki Kanban',codicon:'project'}}
    ]);
  }
};
