from typing import Literal

from pydantic import BaseModel, Field


Language = Literal["en", "fa"]


class ManagementQuestionRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    question_id: str = Field(pattern=r"^MQ-(0[1-9]|1[0-9]|20)$")
    language: Language = "en"


QUESTIONS = [
    ("MQ-01", "overall_status", "operations", "What is the exchange's current overall status?", "وضعیت کلی فعلی صرافی چیست؟", ["legacy_dashboard"]),
    ("MQ-02", "priorities", "executive", "What are today's highest management priorities?", "مهم‌ترین اولویت‌های مدیریتی امروز چیست؟", ["executive_brief"]),
    ("MQ-03", "incidents", "operations", "What critical incidents are active?", "چه رخدادهای بحرانی فعالی وجود دارد؟", ["operations_analysis"]),
    ("MQ-04", "pending_withdrawals", "operations", "How many withdrawals are pending?", "چند برداشت در انتظار است؟", ["legacy_dashboard"]),
    ("MQ-05", "withdrawal_trend", "operations", "Is the withdrawal backlog improving or worsening?", "صف برداشت‌ها بهتر شده یا بدتر؟", ["legacy_dashboard"]),
    ("MQ-06", "root_cause", "operations", "What is the confirmed root cause of the main incident?", "علت ریشه‌ای تأییدشده رخداد اصلی چیست؟", ["operations_analysis"]),
    ("MQ-07", "market_condition", "market_risk", "What is the current BTC market condition?", "وضعیت فعلی بازار بیت‌کوین چیست؟", ["legacy_dashboard"]),
    ("MQ-08", "risk_limits", "market_risk", "Are market exposures within approved risk limits?", "آیا مواجهه‌های بازار در حدود ریسک تأییدشده هستند؟", ["market_risk_analysis"]),
    ("MQ-09", "liquidity", "market_risk", "Is market liquidity sufficient?", "آیا نقدشوندگی بازار کافی است؟", ["market_risk_analysis"]),
    ("MQ-10", "liability_coverage", "treasury", "Are customer liabilities fully covered?", "آیا بدهی مشتریان کاملاً پوشش داده شده است؟", ["treasury_analysis"]),
    ("MQ-11", "reconciliation", "treasury", "Are treasury accounts reconciled?", "آیا حساب‌های خزانه‌داری تطبیق داده شده‌اند؟", ["treasury_analysis"]),
    ("MQ-12", "aml_priority", "aml_fraud", "Which AML cases need immediate attention?", "کدام پرونده‌های مبارزه با پول‌شویی نیازمند رسیدگی فوری هستند؟", ["aml_fraud_analysis"]),
    ("MQ-13", "fraud_trend", "aml_fraud", "Is fraud risk increasing or decreasing?", "ریسک تقلب در حال افزایش است یا کاهش؟", ["aml_fraud_analysis"]),
    ("MQ-14", "security_threats", "security", "Are there active security threats?", "آیا تهدید امنیتی فعالی وجود دارد؟", ["security_analysis"]),
    ("MQ-15", "privileged_activity", "security", "Are privileged actions properly authorized?", "آیا اقدامات ممتاز به‌درستی مجاز شده‌اند؟", ["security_analysis"]),
    ("MQ-16", "support_trend", "support", "Which customer-support issues are increasing?", "کدام مشکلات پشتیبانی مشتری در حال افزایش هستند؟", ["support_analysis"]),
    ("MQ-17", "support_sla", "support", "Are customer-support SLAs being met?", "آیا SLAهای پشتیبانی مشتری رعایت می‌شوند؟", ["support_outcome_evaluation"]),
    ("MQ-18", "pilot_readiness", "governance", "Is the system ready for a production pilot?", "آیا سامانه برای پایلوت تولید آماده است؟", ["pilot_manifest"]),
    ("MQ-19", "capability_gaps", "governance", "Which capabilities or data sources are missing?", "کدام قابلیت‌ها یا منابع داده مفقود هستند؟", ["source_contracts"]),
    ("MQ-20", "approval_decisions", "governance", "Which decisions require management approval today?", "کدام تصمیم‌ها امروز به تأیید مدیریت نیاز دارند؟", ["pilot_manifest"]),
]

CATALOG = {
    question_id: {
        "id": question_id, "intent": intent, "domain": domain,
        "question": {"en": english, "fa": persian},
        "required_sources": sources,
    }
    for question_id, intent, domain, english, persian, sources in QUESTIONS
}


def management_question_catalog(language: Language) -> list[dict]:
    return [
        {"id": item["id"], "intent": item["intent"], "domain": item["domain"],
         "question": item["question"][language],
         "required_sources": item["required_sources"]}
        for item in CATALOG.values()
    ]


def _output_evidence(output: dict | None, source: str) -> list[dict]:
    if not output:
        return []
    return [{
        "source": source, "observed_at": output.get("created_at"),
        "owner": output.get("payload", {}).get("owner", "domain owner"),
        "evidence_ref": output.get("output_id"),
        "evidence_hash": output.get("payload_hash"),
    }]


def _payload_summary(payload: dict) -> tuple[str, str, list[str], str]:
    status = str(payload.get("status", "available"))
    severity = str(payload.get("severity", payload.get("overall_severity", "unknown")))
    headline = str(payload.get("headline", payload.get("conclusion", "Audited domain evidence is available.")))
    limitations = [str(item) for item in payload.get("limitations", [])]
    next_action = str(payload.get("recommended_next_action", "Review the cited domain output with its owner."))
    return status, severity, limitations, f"{headline} Status: {status}; severity: {severity}. {next_action}"


def answer_management_question(
    question_id: str, language: Language, context: dict
) -> dict:
    item = CATALOG[question_id]
    outputs = context.get("outputs", {})
    legacy = context.get("legacy")
    pilot = context.get("pilot")
    source_contracts = context.get("source_contracts", {})
    evidence: list[dict] = []
    limitations: list[str] = []
    next_action = "Continue monitored review."
    status = "answered"
    confidence = "high"

    if item["required_sources"] == ["legacy_dashboard"]:
        if not legacy:
            status, confidence = "blocked", "none"
            english = "The retained dashboard evidence is unavailable. Refresh approved live sources first."
            limitations = ["No retained operations and market snapshot is available."]
            next_action = "Refresh the dashboard from approved read-only exchange sources."
        else:
            evidence = [{
                "source": "retained_dashboard", "observed_at": legacy.get("generated_at"),
                "owner": "exchange operations", "evidence_ref": legacy["evidence_record"]["id"],
                "evidence_hash": legacy["evidence_record"]["hash"],
            }]
            operations = legacy["operations"].get("data", {})
            risk = legacy["market_risk"]
            if question_id == "MQ-01":
                english = f"Operations evidence is available with {operations.get('pending_withdrawals')} pending withdrawals. Market evidence severity is {risk.get('severity')} with {risk.get('confidence')} confidence."
            elif question_id == "MQ-04":
                english = f"The latest retained evidence reports {operations.get('pending_withdrawals')} pending withdrawals."
            elif question_id == "MQ-05":
                change = legacy.get("investigation", {}).get("supporting_evidence", {}).get("pending_change")
                english = "The retained window cannot establish the backlog trend." if change is None else f"Pending withdrawals changed by {change} across the retained evidence window."
                if change is None: status, confidence = "partial", "limited"
            else:
                market = legacy["market"].get("data", {})
                valid = risk.get("data_quality", {}).get("valid", False)
                english = (f"{market.get('market')} last price is {market.get('last')} {market.get('quote_asset')}; market evidence is {'valid' if valid else 'incomplete'} and risk confidence is {risk.get('confidence')}." )
                if not valid: status, confidence = "partial", "insufficient"
                limitations = list(risk.get("limitations", []))
            next_action = "Review the retained evidence and source-quality flags."
    elif item["required_sources"] == ["pilot_manifest"]:
        if not pilot:
            status, confidence = "blocked", "none"
            english = "Pilot readiness evidence is unavailable."
            limitations = ["No pilot manifest was evaluated."]
        elif question_id == "MQ-18":
            english = f"The pilot decision is {pilot.get('decision')}: {pilot.get('passed', 0)} of {pilot.get('total', 0)} mandatory gates pass."
            if not pilot.get("approved"): status, confidence = "partial", "high"
            limitations = [gate["id"] for gate in pilot.get("blockers", [])]
        else:
            blockers = [gate["id"] for gate in pilot.get("blockers", [])]
            english = "Management approval or remediation is required for: " + (", ".join(blockers) or "no outstanding pilot gates") + "."
            if blockers: status = "partial"
            limitations = blockers
        next_action = "Resolve blocker evidence with the named owners before a go/no-go decision."
        evidence = [{"source": "pilot_manifest", "observed_at": pilot.get("generated_at"),
                     "owner": "steering committee", "evidence_ref": pilot.get("evidence_sha256"),
                     "evidence_hash": pilot.get("evidence_sha256")}]
    elif item["required_sources"] == ["source_contracts"]:
        missing = source_contracts.get("missing", [])
        english = f"{len(missing)} required upstream sources remain unavailable: " + ", ".join(missing) + "."
        status = "partial" if missing else "answered"
        confidence = "high"
        limitations = missing
        next_action = "Ask the exchange source owners to implement and approve the missing contracts."
        evidence = source_contracts.get("evidence", [])
    else:
        output_type = item["required_sources"][0]
        output = outputs.get(output_type)
        if not output:
            status, confidence = "blocked", "none"
            english = f"No current audited {item['domain']} output is available for this question."
            limitations = [f"Missing required source: {output_type}"]
            next_action = f"Connect and run the approved {item['domain']} analysis source."
        else:
            domain_status, severity, limitations, english = _payload_summary(output["payload"])
            if domain_status not in {"ready", "available"} or severity == "unknown":
                status, confidence = "partial", "limited"
            next_action = str(output["payload"].get("recommended_next_action", "Review the cited domain output with its owner."))
            evidence = _output_evidence(output, output_type)

    if language == "fa":
        state = {"answered": "پاسخ موجود است", "partial": "پاسخ ناقص است", "blocked": "پاسخ مسدود است"}[status]
        source_names = "، ".join(item["required_sources"])
        persian_base = {
            "MQ-01": "شواهد عملیات و وضعیت بازار در جمع‌بندی مدیریتی بررسی شد.",
            "MQ-02": "اولویت‌ها از آخرین خلاصه اجرایی ممیزی‌شده استخراج شده‌اند.",
            "MQ-03": "رخدادها از آخرین تحلیل عملیات ممیزی‌شده بررسی شده‌اند.",
            "MQ-04": english.replace("The latest retained evidence reports", "آخرین شواهد نگهداری‌شده").replace("pending withdrawals.", "برداشت معلق را گزارش می‌کند."),
            "MQ-05": "روند صف برداشت از پنجره شواهد نگهداری‌شده ارزیابی شد.",
            "MQ-06": "تنها علت‌های تأییدشده در تحلیل عملیات قابل گزارش هستند؛ فرضیه بدون تأیید به‌عنوان علت قطعی ارائه نمی‌شود.",
            "MQ-07": "وضعیت بازار بیت‌کوین با کنترل کیفیت قیمت و ریسک ارزیابی شد.",
            "MQ-08": "مواجهه و حدود ریسک از آخرین تحلیل بازار و ریسک بررسی شد.",
            "MQ-09": "نقدشوندگی از شواهد عمق، اختلاف قیمت و کیفیت بازار بررسی شد.",
            "MQ-10": "پوشش بدهی مشتریان از آخرین تحلیل خزانه‌داری بررسی شد.",
            "MQ-11": "وضعیت تطبیق از آخرین تحلیل خزانه‌داری بررسی شد.",
            "MQ-12": "اولویت پرونده‌ها از آخرین تحلیل مبارزه با پول‌شویی بررسی شد.",
            "MQ-13": "روند ریسک تقلب از خروجی ممیزی‌شده مبارزه با پول‌شویی بررسی شد.",
            "MQ-14": "تهدیدهای فعال از آخرین تحلیل امنیت بررسی شدند.",
            "MQ-15": "مجوز فعالیت ممتاز از آخرین تحلیل امنیت بررسی شد.",
            "MQ-16": "روند مشکلات مشتری از آخرین تحلیل پشتیبانی بررسی شد.",
            "MQ-17": "رعایت SLA از آخرین ارزیابی نتایج پشتیبانی بررسی شد.",
            "MQ-18": f"تصمیم پایلوت {pilot.get('decision') if pilot else 'ناموجود'} است و {pilot.get('passed', 0) if pilot else 0} از {pilot.get('total', 0) if pilot else 0} دروازه عبور کرده‌اند.",
            "MQ-19": f"{len(source_contracts.get('missing', []))} منبع بالادستی الزامی هنوز موجود نیست.",
            "MQ-20": "تصمیم‌های دارای دروازه مسدود برای تأیید یا رفع نقص مدیریت ارائه شده‌اند.",
        }[question_id]
        answer = f"{persian_base} {state}. منبع لازم: {source_names}."
        next_action = "شواهد و محدودیت‌های ارجاع‌شده را با مالک حوزه بررسی کنید."
    else:
        answer = english

    if not evidence:
        evidence = [context.get("gap_evidence", {
            "source": "management_source_gap", "observed_at": None,
            "owner": f"{item['domain']} owner", "evidence_ref": item["required_sources"][0],
            "evidence_hash": "0" * 64,
        })]
    return {
        "question_id": question_id, "intent": item["intent"],
        "domain": item["domain"], "language": language,
        "question": item["question"][language], "status": status,
        "answer": answer, "confidence": confidence,
        "evidence": evidence, "limitations": limitations,
        "owner": evidence[0]["owner"] if evidence else f"{item['domain']} owner",
        "next_action": next_action, "action_executed": False,
    }
