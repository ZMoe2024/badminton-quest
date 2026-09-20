package cn.badmintonquest.mobile;

import android.app.AlertDialog;
import android.content.*;
import android.net.Uri;
import android.os.*;
import org.json.JSONObject;

public class MainActivity extends ShellActivity {
    private static final int SCHOOL_REQUEST=42;
    private String credentials;
    private final Handler timer=new Handler(Looper.getMainLooper());
    private final Runnable expire=()->{credentials=null;if(status!=null)status.setText("临时提取结果已清除；已保存到网站的会话不受影响。");};
    @Override public void onCreate(Bundle state){
        super.onCreate(state);buildShell("羽球训练家","BADMINTON QUEST  ·  MOBILE 0.1");
        status.setText("先登录预约网站账号，再点「学校登录」。");
        web.setWebViewClient(client());
        button("学校登录",()->startActivityForResult(new Intent(this,SchoolActivity.class),SCHOOL_REQUEST));
        button("导入会话",this::showImport);
        button("刷新网页",()->web.reload());
        web.loadUrl(Hosts.WEBSITE+"/");
    }
    @Override protected boolean allow(String url){
        if(Hosts.website(url))return true;
        if(url.startsWith("https://"))new AlertDialog.Builder(this).setMessage("在系统浏览器打开外部链接？").setNegativeButton("取消",null).setPositiveButton("打开",(d,w)->{try{startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(url)));}catch(Exception e){status.setText("未找到可打开此链接的浏览器。");}}).show();
        else status.setText("此链接无法在预约窗口内打开。");
        return false;
    }
    @Override protected void onActivityResult(int request,int result,Intent data){
        super.onActivityResult(request,result,data);
        if(request==SCHOOL_REQUEST&&result==RESULT_OK&&data!=null){
            String value=data.getStringExtra("credentials");
            if(value==null||value.length()>90000)return;
            credentials=value;timer.removeCallbacks(expire);timer.postDelayed(expire,5*60*1000);
            status.setText("已提取本次学校会话，等待网站验证。");showImport();
        }
    }
    private void showImport(){
        if(credentials==null){status.setText("还没有提取结果，请先点「学校登录」。");return;}
        new AlertDialog.Builder(this).setTitle("把会话交给当前网站账号？")
            .setMessage("将填入羽球训练家的登录设置。请核对网页账号，再点「验证并保存」。这不会预约或付款。")
            .setPositiveButton("填入网站",(d,w)->stage())
            .setNeutralButton("只复制",(d,w)->copy())
            .setNegativeButton("稍后",null).show();
    }
    private void stage(){
        if(credentials==null)return;
        if(!Hosts.website(web.getUrl())){status.setText("请先返回预约网站并登录自己的账号。");return;}
        String js="(()=>{if(location.origin!=="+JSONObject.quote(Hosts.WEBSITE)+")return false;return !!window.QuestMobile?.stage("+JSONObject.quote(credentials)+");})()";
        web.evaluateJavascript(js,value->status.setText("true".equals(value)?"已请求填入。请核对网页中的账号与内容，再点验证并保存。":"请先登录网站并等待页面查询结束，然后再点「导入会话」。"));
    }
    private void copy(){
        if(credentials==null)return;
        ClipData clip=ClipData.newPlainText("学校会话（请勿分享）",credentials);
        if(Build.VERSION.SDK_INT>=33){PersistableBundle extras=new PersistableBundle();extras.putBoolean("android.content.extra.IS_SENSITIVE",true);clip.getDescription().setExtras(extras);}
        ((ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(clip);
        status.setText("已复制。仅粘贴到你自己的羽球训练家登录设置。");
    }
    @Override protected void onDestroy(){timer.removeCallbacks(expire);credentials=null;super.onDestroy();}
}
