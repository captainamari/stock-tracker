"""Request-local presentation; never mutate global template filters in a request."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi.templating import Jinja2Templates
from web.i18n import get_language_from_request
from web.auth import session
from lib.settings import settings
from lib.market_calendar import completed_session
from lib.listing import near, score

templates = Jinja2Templates(directory=str(Path(__file__).parent/'templates'))
templates.env.filters['price'] = lambda v: '—' if v is None else f'${v:,.2f}'
templates.env.filters['number'] = lambda v: '—' if v is None else f'{v:,.2f}' if isinstance(v,(int,float)) else v
templates.env.filters['pct'] = lambda v: '—' if v is None else f'{v:+.2f}%'


def spark_path(values):
    valid = [v for v in values if v is not None]
    if not valid or len(values) < 2:
        return ''
    low, high = min(valid), max(valid)
    path, connected = [], False
    for i, value in enumerate(values):
        if value is None:
            connected = False
            continue
        x = 2 + i * 136 / (len(values)-1)
        y = 18 if high == low else 34 - (value-low) * 32 / (high-low)
        path.append(f'{"L" if connected else "M"}{x:.1f},{y:.1f}')
        connected = True
    return ' '.join(path)


templates.env.filters['spark_path'] = spark_path
NAMES = {'stage2_us':('Stage 2','Stage 2 趋势'), 'contraction_us':('Contraction candidates','收缩候选'),
         'bottom_fisher_us':('Countertrend watch','逆势观察'), 'checklist_us':('Checklist','条件清单')}
STATUS = {'ok':('Available','可用'),'pending':('Pending update','待更新'),'insufficient_data':('Insufficient data','数据不足'),
          'stale':('Stale','过期'),'failed':('Failed','失败'),'queued':('Queued','排队中'),'running':('Running','运行中'),
          'published':('Published','已发布'),'sent':('Sent','已投递'),'partial':('Partially delivered','部分投递'),
          'unknown':('Delivery uncertain','投递结果未知'),'retryable':('Waiting to retry','等待重试'),'blocked':('Needs configuration','需配置'),
          'sending':('Sending','发送中'),'resolved':('Resolved without resend','已处理，未重发')}

CONDITIONS = {
 'stage2_us': [('Price > SMA150 and SMA200','价格高于 SMA150 和 SMA200'),('SMA150 > SMA200','SMA150 高于 SMA200'),('SMA200 rising over 20 sessions','SMA200 较20个交易日前上升'),('SMA50 > SMA150 and SMA200','SMA50 高于 SMA150 和 SMA200'),('Price > SMA50','价格高于 SMA50'),('Price > 52-week low × 1.25','价格高于52周低点的1.25倍'),('Price > 52-week high × 0.75','价格高于52周高点的0.75倍'),('126-session return > SPY on aligned dates','同日期126交易日回报高于 SPY')],
 'contraction_us': [('52-week drawdown ≥ −25%','52周高点回撤不超过25%'),('20-session drawdown ≥ −10%','20日高点回撤不超过10%'),('Bandwidth percentile ≤ 25','布林带宽分位不超过25'),('Volume ratio < 0.75; ≥4/5 dry days','量比低于0.75，5天至少4天缩量'),('SMA50 rising over 20 sessions','SMA50 较20个交易日前上升'),('Within 3% of SMA10','距 SMA10 不超过3%')],
 'bottom_fisher_us': [('Within −15% / +10% of SMA200','距 SMA200 在−15%至+10%'),('Trend quality or prior Stage2 entry','趋势质地或历史 Stage2 记录'),('52-week drawdown ≤ −15%','52周回撤至少15%'),('20-session drawdown ≤ −8%','20日回撤至少8%'),('Within 3% of support','距支撑不超过3%'),('RSI oversold or bullish divergence','RSI 超卖或底背离'),('Volume ratio < 0.6','量比低于0.6'),('MACD bullish divergence','MACD 底背离')],
 'checklist_us': [('Weekly impulse green (provisional week)','周线冲量为绿（含本周暂态）'),('EMA10 > EMA21','EMA10 高于 EMA21'),('SMA50 > SMA200','SMA50 高于 SMA200'),('RSI between 40 and 70','RSI 在40至70'),('MACD positive / improving','MACD 为正或改善'),('Price above SMA50 and SMA200','价格高于 SMA50 和 SMA200'),('52-week drawdown ≥ −25%','52周回撤不超过25%'),('At least 10% above 52-week low','距52周低点至少上涨10%'),('10/50-day volume ratio ≥ 1','10/50日量比至少为1'),('Volume expansion in last three days','近3日有放量'),('Stage2 confirmed in this batch','同批次 Stage2 已确认')]
}


def context(request):
    lang = get_language_from_request(request)
    def t(en,zh):
        return zh if lang=='zh' else en
    def label(key):
        return t(*STATUS.get(key,(key or '—',key or '—')))
    def regime_label(key):
        values={'bullish':('Bullish','偏多'),'bearish':('Bearish','偏空'),'neutral':('Neutral','中性'),'caution':('Caution','谨慎'),'risk_on':('Risk on','风险偏好'),'risk_off':('Risk off','风险回避')}
        return t(*values.get(key,(key,key))) if key else t('Unavailable: required inputs missing','不可用：必要输入缺失')
    def group_label(key):
        values={'moving_averages':('Moving averages','移动均线'),'momentum':('Momentum','动量'),'support_resistance':('Support and resistance','支撑与阻力'),'fibonacci':('Fibonacci levels','斐波那契水平')}
        return t(*values.get(key,(key,key)))
    def local_time(value):
        return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(ZoneInfo(settings().display_timezone)).strftime('%Y-%m-%d %H:%M %Z') if value else '—'
    return dict(lang=lang,t=t,status_label=label,near=near,strategy_score=score,names={s:t(*v) for s,v in NAMES.items()},
                condition_names={s:[t(*v) for v in names] for s,names in CONDITIONS.items()},
                admin=bool(session(request)),local_time=local_time,expected_date=completed_session(),regime_label=regime_label,group_label=group_label,
                display_timezone=settings().display_timezone)


def render(request,template,data=None):
    return templates.TemplateResponse(request=request,name=template,context={**context(request),**(data or {})})
