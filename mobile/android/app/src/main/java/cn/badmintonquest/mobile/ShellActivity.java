package cn.badmintonquest.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.http.SslError;
import android.view.Gravity;
import android.view.View;
import android.webkit.*;
import android.widget.*;

public abstract class ShellActivity extends Activity {
    protected WebView web;
    protected TextView status;
    protected LinearLayout actions;
    protected final int ink=Color.rgb(37,48,68),cream=Color.rgb(255,247,229),red=Color.rgb(207,62,80);
    protected int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
    protected void buildShell(String title,String label){
        LinearLayout root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setBackgroundColor(cream);
        root.setOnApplyWindowInsetsListener((v,insets)->{v.setPadding(0,insets.getSystemWindowInsetTop(),0,insets.getSystemWindowInsetBottom());return insets;});
        TextView heading=new TextView(this);heading.setText("◉  "+title);heading.setTextColor(ink);heading.setTextSize(20);heading.setTypeface(Typeface.DEFAULT,Typeface.BOLD);heading.setPadding(dp(16),dp(10),dp(16),dp(6));root.addView(heading);
        TextView sub=new TextView(this);sub.setText(label);sub.setTextColor(ink);sub.setTextSize(11);sub.setTypeface(Typeface.MONOSPACE);sub.setPadding(dp(16),0,dp(16),dp(10));root.addView(sub);
        View line=new View(this);line.setBackgroundColor(red);root.addView(line,new LinearLayout.LayoutParams(-1,dp(3)));
        ProgressBar progress=new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal);progress.setMax(100);root.addView(progress,new LinearLayout.LayoutParams(-1,dp(3)));
        web=new WebView(this);web.setBackgroundColor(cream);root.addView(web,new LinearLayout.LayoutParams(-1,0,1));
        WebSettings settings=web.getSettings();settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSafeBrowsingEnabled(true);settings.setSupportMultipleWindows(false);
        web.setWebChromeClient(new WebChromeClient(){
            @Override public void onProgressChanged(WebView view,int value){progress.setProgress(value);progress.setVisibility(value==100?View.INVISIBLE:View.VISIBLE);}
            @Override public boolean onJsAlert(WebView v,String url,String text,JsResult result){new AlertDialog.Builder(ShellActivity.this).setMessage(text).setPositiveButton("确定",(d,w)->result.confirm()).setOnCancelListener(d->result.cancel()).show();return true;}
            @Override public boolean onJsConfirm(WebView v,String url,String text,JsResult result){new AlertDialog.Builder(ShellActivity.this).setMessage(text).setPositiveButton("确定",(d,w)->result.confirm()).setNegativeButton("取消",(d,w)->result.cancel()).setOnCancelListener(d->result.cancel()).show();return true;}
        });
        status=new TextView(this);status.setTextColor(ink);status.setTextSize(12);status.setPadding(dp(14),dp(9),dp(14),dp(6));root.addView(status);
        actions=new LinearLayout(this);actions.setGravity(Gravity.CENTER);actions.setPadding(dp(8),0,dp(8),dp(8));root.addView(actions);
        setContentView(root);root.requestApplyInsets();
    }
    protected Button button(String label,Runnable click){
        Button button=new Button(this);button.setText(label);button.setTextSize(13);button.setAllCaps(false);button.setTextColor(ink);button.setMinHeight(dp(48));button.setPadding(dp(4),0,dp(4),0);
        GradientDrawable bg=new GradientDrawable();bg.setColor(cream);bg.setCornerRadius(dp(5));bg.setStroke(dp(2),ink);button.setBackground(bg);
        LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(0,dp(48),1);params.setMargins(dp(4),dp(3),dp(4),dp(3));actions.addView(button,params);button.setOnClickListener(v->click.run());return button;
    }
    protected WebViewClient client(){return new WebViewClient(){
        @Override public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest r){return !allow(r.getUrl().toString());}
        @Override public void onReceivedError(WebView v,WebResourceRequest r,WebResourceError e){if(r.isForMainFrame())status.setText("页面未能打开，请检查网络后重试。");}
        @Override public void onReceivedHttpError(WebView v,WebResourceRequest r,WebResourceResponse response){if(r.isForMainFrame())status.setText("页面返回 HTTP "+response.getStatusCode()+"。请重试；未提取任何会话。");}
        @Override public void onReceivedSslError(WebView v,SslErrorHandler handler,SslError error){handler.cancel();status.setText("网站证书验证失败，已停止打开。");}
    };}
    protected abstract boolean allow(String url);
    @Override public void onBackPressed(){if(web!=null&&web.canGoBack())web.goBack();else super.onBackPressed();}
    @Override protected void onDestroy(){if(web!=null){web.stopLoading();web.destroy();}super.onDestroy();}
}
