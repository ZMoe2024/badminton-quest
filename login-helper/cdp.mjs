export class CDP {
  constructor(socket) {
    this.socket=socket;this.next=0;this.pending=new Map();this.listeners=new Set();
    socket.addEventListener('message', event => {
      const data=JSON.parse(event.data);
      if(data.id){
        const entry=this.pending.get(data.id);if(!entry)return;
        this.pending.delete(data.id);clearTimeout(entry.timer);
        data.error ? entry.reject(Error('浏览器操作失败：'+data.error.message)) : entry.resolve(data.result);
      }else for(const handler of this.listeners)handler(data);
    });
    socket.addEventListener('close',()=>{
      for(const entry of this.pending.values()){clearTimeout(entry.timer);entry.reject(Error('登录窗口已关闭。'));}
      this.pending.clear();
    });
  }
  static async connect(url) {
    const parsed=new URL(url);
    if(parsed.protocol!=='ws:'||parsed.hostname!=='127.0.0.1')throw Error('只允许连接本次启动的本地登录浏览器。');
    const socket=new WebSocket(url);
    await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{socket.close();reject(Error('连接登录窗口超时。'));},10000);
      socket.addEventListener('open',()=>{clearTimeout(timer);resolve();},{once:true});
      socket.addEventListener('error',()=>{clearTimeout(timer);reject(Error('无法连接登录窗口。'));},{once:true});
    });
    return new CDP(socket);
  }
  send(method,params={},sessionId) {
    if(this.socket.readyState!==WebSocket.OPEN)return Promise.reject(Error('登录窗口已关闭。'));
    const id=++this.next;
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{this.pending.delete(id);reject(Error('浏览器响应超时。'));},7000);
      this.pending.set(id,{resolve,reject,timer});
      this.socket.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));
    });
  }
  close(){this.socket.close();}
}
