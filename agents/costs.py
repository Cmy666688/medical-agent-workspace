"""Observed cost records and explicitly labelled historical reference estimates."""
import math


def number(value):
    if isinstance(value,bool):return None
    try:result=float(value)
    except (TypeError,ValueError):return None
    return result if math.isfinite(result) and result>=0 else None


def cost_rows(rows,config):
    result=[]
    for row in rows:
        value=dict(row)
        amount=number(row.get('cost'))
        currency=row.get('price_currency') if isinstance(row.get('price_currency'),str) else ''
        status='已记录估算'
        if amount is None:
            inp=number(row.get('input_tokens'));out=number(row.get('output_tokens'))
            if inp is None or out is None:status='缺少 token 用量'
            elif row.get('model')==config.model and row.get('provider')=='primary' and (config.input_price or config.output_price):
                amount=(inp*config.input_price+out*config.output_price)/1_000_000
                currency=config.price_currency
                status='历史按当前单价参考估算'
            else:status='缺少适用单价'
        value.update(计价状态=status,币种=currency or '未指定币种',估算成本=amount)
        result.append(value)
    return result


def cost_summary(rows,config):
    annotated=cost_rows(rows,config)
    totals={}
    for row in annotated:
        if row['估算成本'] is not None:totals[row['币种']]=totals.get(row['币种'],0)+row['估算成本']
    return dict(rows=annotated,totals=totals,total=len(annotated),
                recorded=sum(row['计价状态']=='已记录估算' for row in annotated),
                historical=sum(row['计价状态']=='历史按当前单价参考估算' for row in annotated),
                missing_usage=sum(row['计价状态']=='缺少 token 用量' for row in annotated),
                missing_price=sum(row['计价状态']=='缺少适用单价' for row in annotated))
