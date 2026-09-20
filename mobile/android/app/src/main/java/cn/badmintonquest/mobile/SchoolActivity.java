package cn.badmintonquest.mobile;

import android.content.Intent;
import android.os.Bundle;
import android.webkit.CookieManager;
import android.webkit.WebStorage;
import android.webkit.WebView;
import org.json.*;
import java.nio.charset.StandardCharsets;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;

public class SchoolActivity extends ShellActivity {
    private static boolean directorySelected=false;
    private boolean reading=false;
    @Override public void onCreate(Bundle state){
        super.onCreate(state);
        if(!directorySelected){WebView.setDataDirectorySuffix("school-login");directorySelected=true;}
        buildShell("连接学校账号","本机独立窗口 · 完成学校认证后返回预约首页");
        status.setText("请在学校原网页登录；完成后点下方按钮。");
        CookieManager manager=CookieManager.getInstance();manager.setAcceptCookie(true);manager.setAcceptThirdPartyCookies(web,true);
        web.setWebViewClient(client());
        button("返回",this::finish);button("完成登录",this::collect);button("重试",()->web.loadUrl(Hosts.SCHOOL+"/"));
        manager.removeAllCookies(done->{if(!isFinishing()&&!isDestroyed())web.loadUrl(Hosts.SCHOOL+"/");});
    }
    @Override protected boolean allow(String url){
        if(Hosts.school(url))return true;
        status.setText("学校跳转到暂未支持的入口，请尝试页面上的其他认证方式。");return false;
    }
    private void collect(){
        if(reading)return;
        if(!Hosts.app(web.getUrl())){status.setText("请先完成学校认证，返回预约首页后再提取。");return;}
        reading=true;status.setText("正在读取本次学校会话…");
        try(InputStream source=getAssets().open("collect.js")){
            ByteArrayOutputStream buffer=new ByteArrayOutputStream();byte[] chunk=new byte[4096];int size;
            while((size=source.read(chunk))!=-1)buffer.write(chunk,0,size);
            String script=buffer.toString(StandardCharsets.UTF_8.name());
            web.evaluateJavascript(script,raw->{
                reading=false;
                if(isFinishing()||isDestroyed()||!Hosts.app(web.getUrl()))return;
                try{
                    JSONObject data=new JSONObject(raw);
                    if(!data.optBoolean("ok")){status.setText(data.optString("message","请先完成学校登录。"));return;}
                    String cookie=CookieManager.getInstance().getCookie(Hosts.SCHOOL+"/");
                    JSONArray rows=cookies(cookie,"resm.lzjtu.edu.cn");
                    boolean bo=false,bp=false;
                    for(int i=0;i<rows.length();i++){JSONObject c=rows.getJSONObject(i);if(!c.getString("value").isEmpty()){bo|=c.getString("name").equals("evbSrBv8QGpBO");bp|=c.getString("name").equals("evbSrBv8QGpBP");}}
                    if(!bo||!bp){status.setText("学校页面初始化尚未完成。请重试，或检查是否出现白屏。");return;}
                    JSONObject output=new JSONObject().put("cookies",rows).put("token",data.getString("token")).put("currentUser",data.getJSONObject("currentUser")).put("userAgent",data.getString("userAgent"));
                    output.put("ssoCookies",cookies(CookieManager.getInstance().getCookie("https://authserver.lzjtu.edu.cn/authserver/"),"authserver.lzjtu.edu.cn"));
                    if(output.toString().getBytes(StandardCharsets.UTF_8).length>90000){status.setText("会话内容过大，未导出。");return;}
                    setResult(RESULT_OK,new Intent().putExtra("credentials",output.toString()));finish();
                }catch(Exception e){status.setText("还未读取到完整会话，请进入预约首页后重试。");}
            });
        }catch(Exception e){reading=false;status.setText("提取组件未能读取，请重新安装最新版本。");}
    }
    private JSONArray cookies(String header,String domain)throws JSONException{
        JSONArray rows=new JSONArray();if(header==null)return rows;
        for(String part:header.split(";")){int at=part.indexOf('=');if(at<1)continue;
            rows.put(new JSONObject().put("name",part.substring(0,at).trim()).put("value",part.substring(at+1).trim()).put("domain",domain).put("path","/").put("secure",true).put("expires",-1));
        }return rows;
    }
    @Override protected void onDestroy(){
        CookieManager.getInstance().removeAllCookies(done->CookieManager.getInstance().flush());
        WebStorage.getInstance().deleteAllData();super.onDestroy();
    }
}
