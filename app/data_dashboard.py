from __future__ import annotations

from typing import Any, Callable

DATA_DASHBOARD_ROLE_LABELS = {'COMPLIANCE_MANAGER': '법무 / 컴플라이언스',
 'CS_STAFF': 'CS 고객서비스',
 'EXECUTIVE': '경영진 종합',
 'FINANCE_MANAGER': '재무',
 'HR_MANAGER': '인사 / 총무 / IT',
 'MARKETING_STAFF': '마케팅',
 'PRODUCTION_MANAGER': '제조 / 생산',
 'QA_MANAGER': 'QA 품질관리',
 'RND_MANAGER': 'R&D 제품개발',
 'SCM_MANAGER': 'SCM 공급망'}

COMMON_DASHBOARD_METRICS = [{'id': 'common_departments',
  'sql': '\n'
         '            SELECT department_name, headcount\n'
         '            FROM cos_adb.silver.departments\n'
         '            ORDER BY headcount DESC\n'
         '        ',
  'table': 'cos_adb.silver.departments',
  'title': '부서별 인원 현황',
  'visualization': '도넛'},
 {'id': 'common_events',
  'sql': '\n'
         '            SELECT event_type, status, COUNT(*) AS event_count\n'
         '            FROM cos_adb.silver.events\n'
         '            GROUP BY event_type, status\n'
         '            ORDER BY event_count DESC\n'
         '            LIMIT 20\n'
         '        ',
  'table': 'cos_adb.silver.events',
  'title': '이벤트/프로젝트 현황',
  'visualization': '목록'}]

ROLE_DASHBOARD_METRICS = {'COMPLIANCE_MANAGER': [{'id': 'legal_audit_findings',
                         'sql': '\n'
                                '                SELECT audit_area,\n'
                                '                       finding_level,\n'
                                '                       COUNT(*) AS finding_count\n'
                                '                FROM cos_adb.silver.legal_compliance_audit_log\n'
                                '                GROUP BY audit_area, finding_level\n'
                                '                ORDER BY finding_count DESC\n'
                                '            ',
                         'table': 'cos_adb.silver.legal_compliance_audit_log',
                         'title': '감사 지적 현황',
                         'visualization': '상태 테이블'},
                        {'id': 'legal_contract_expiry',
                         'sql': '\n'
                                '                SELECT contract_type,\n'
                                '                       CASE\n'
                                "                         WHEN expiry_date < current_date() THEN 'EXPIRED'\n"
                                '                         WHEN expiry_date <= date_add(current_date(), 90) THEN '
                                "'DUE_90D'\n"
                                "                         ELSE 'ACTIVE'\n"
                                '                       END AS expiry_status,\n'
                                '                       COUNT(*) AS contract_count\n'
                                '                FROM cos_adb.silver.legal_contract_metadata\n'
                                '                GROUP BY contract_type,\n'
                                '                         CASE\n'
                                "                           WHEN expiry_date < current_date() THEN 'EXPIRED'\n"
                                '                           WHEN expiry_date <= date_add(current_date(), 90) THEN '
                                "'DUE_90D'\n"
                                "                           ELSE 'ACTIVE'\n"
                                '                         END\n'
                                '                ORDER BY contract_count DESC\n'
                                '            ',
                         'table': 'cos_adb.silver.legal_contract_metadata',
                         'title': '계약 만료 리스크',
                         'visualization': '상태 바'},
                        {'id': 'legal_document_inventory',
                         'sql': '\n'
                                '                SELECT document_group,\n'
                                '                       COUNT(*) AS document_count\n'
                                '                FROM (\n'
                                "                  SELECT 'REGULATORY' AS document_group\n"
                                '                  FROM cos_adb.silver.legal_regulatory_documents\n'
                                '                  UNION ALL\n'
                                "                  SELECT 'PRIVACY' AS document_group\n"
                                '                  FROM cos_adb.silver.legal_privacy_policy_documents\n'
                                '                  UNION ALL\n'
                                "                  SELECT 'CONTRACT' AS document_group\n"
                                '                  FROM cos_adb.silver.legal_contract_metadata\n'
                                '                ) docs\n'
                                '                GROUP BY document_group\n'
                                '                ORDER BY document_count DESC\n'
                                '            ',
                         'table': 'cos_adb.silver.legal_regulatory_documents',
                         'title': '법무 문서 인벤토리',
                         'visualization': '도넛'}],
 'CS_STAFF': [{'id': 'cs_inquiries',
               'sql': '\n'
                      '                SELECT inquiry_type, status, COUNT(*) AS inquiry_count\n'
                      '                FROM cos_adb.silver.cs_customer_inquiries\n'
                      '                GROUP BY inquiry_type, status\n'
                      '                ORDER BY inquiry_count DESC\n'
                      '            ',
               'table': 'cos_adb.silver.cs_customer_inquiries',
               'title': '고객 문의 유형/상태',
               'visualization': '스택 바'},
              {'id': 'cs_voc_signal',
               'sql': '\n'
                      '                SELECT product_name,\n'
                      '                       ROUND(AVG(sentiment_score), 4) AS avg_sentiment_score,\n'
                      '                       SUM(skin_reaction_mentions) AS skin_reaction_mentions,\n'
                      '                       MAX(claim_signal_level) AS claim_signal_level\n'
                      '                FROM cos_adb.silver.voc_review_voc_insights\n'
                      '                GROUP BY product_name\n'
                      '                ORDER BY skin_reaction_mentions DESC\n'
                      '                LIMIT 20\n'
                      '            ',
               'table': 'cos_adb.silver.voc_review_voc_insights',
               'title': 'VOC 감성/피부반응',
               'visualization': '경보 테이블'},
              {'id': 'cs_rating_trend',
               'sql': '\n'
                      '                SELECT product_name, period, ROUND(AVG(average_rating), 3) AS average_rating\n'
                      '                FROM cos_adb.silver.voc_review_voc_insights\n'
                      '                GROUP BY product_name, period\n'
                      '                ORDER BY period DESC, product_name\n'
                      '                LIMIT 30\n'
                      '            ',
               'table': 'cos_adb.silver.voc_review_voc_insights',
               'title': '제품별 평점 추이',
               'visualization': '라인 차트'}],
 'EXECUTIVE': [{'id': 'exec_sales_margin',
                'sql': '\n'
                       '                SELECT channel,\n'
                       '                       SUM(net_sales_krw) AS net_sales_krw,\n'
                       '                       ROUND(AVG(gross_margin_rate), 4) AS avg_gross_margin_rate\n'
                       '                FROM cos_adb.silver.fin_sales_summary\n'
                       '                GROUP BY channel\n'
                       '                ORDER BY net_sales_krw DESC\n'
                       '            ',
                'table': 'cos_adb.silver.fin_sales_summary',
                'title': '전사 채널 매출/마진',
                'visualization': '상태 바'},
               {'id': 'exec_quality_risk',
                'sql': '\n'
                       '                SELECT severity, COUNT(*) AS deviation_count\n'
                       '                FROM cos_adb.silver.qa_deviation_reports\n'
                       '                GROUP BY severity\n'
                       '                ORDER BY deviation_count DESC\n'
                       '            ',
                'table': 'cos_adb.silver.qa_deviation_reports',
                'title': '품질 리스크 스코어',
                'visualization': '상태 바'},
               {'id': 'exec_qc_pass',
                'sql': '\n'
                       '                SELECT result_status, COUNT(*) AS result_count\n'
                       '                FROM cos_adb.silver.qa_qc_test_results\n'
                       '                GROUP BY result_status\n'
                       '                ORDER BY result_count DESC\n'
                       '            ',
                'table': 'cos_adb.silver.qa_qc_test_results',
                'title': 'QC 합격률',
                'visualization': '상태 바'},
               {'id': 'exec_rnd_pipeline',
                'sql': '\n'
                       '                SELECT launch_status, product_line, COUNT(*) AS product_count\n'
                       '                FROM cos_adb.silver.rnd_product_master\n'
                       '                GROUP BY launch_status, product_line\n'
                       '                ORDER BY product_count DESC\n'
                       '            ',
                'table': 'cos_adb.silver.rnd_product_master',
                'title': 'R&D 파이프라인',
                'visualization': '상태 바'},
               {'id': 'exec_supply_health',
                'sql': '\n'
                       "                SELECT CASE WHEN available_quantity_kg <= reorder_threshold_kg THEN 'REORDER' "
                       "ELSE 'OK' END AS inventory_status,\n"
                       '                       COUNT(*) AS material_count\n'
                       '                FROM cos_adb.silver.scm_raw_material_inventory\n'
                       '                GROUP BY CASE WHEN available_quantity_kg <= reorder_threshold_kg THEN '
                       "'REORDER' ELSE 'OK' END\n"
                       '            ',
                'table': 'cos_adb.silver.scm_raw_material_inventory',
                'title': '공급망 건강도',
                'visualization': '상태 바'},
               {'id': 'exec_audit',
                'sql': '\n'
                       '                SELECT audit_area, finding_level, COUNT(*) AS finding_count\n'
                       '                FROM cos_adb.silver.legal_compliance_audit_log\n'
                       '                GROUP BY audit_area, finding_level\n'
                       '                ORDER BY finding_count DESC\n'
                       '                LIMIT 20\n'
                       '            ',
                'table': 'cos_adb.silver.legal_compliance_audit_log',
                'title': '컴플라이언스 감사',
                'visualization': '상태 테이블'}],
 'FINANCE_MANAGER': [{'id': 'fin_sales_trend',
                      'sql': '\n'
                             '                SELECT channel,\n'
                             '                       SUM(net_sales_krw) AS net_sales_krw,\n'
                             '                       ROUND(AVG(gross_margin_rate), 4) AS avg_gross_margin_rate\n'
                             '                FROM cos_adb.silver.fin_sales_summary\n'
                             '                GROUP BY channel\n'
                             '                ORDER BY net_sales_krw DESC\n'
                             '            ',
                      'table': 'cos_adb.silver.fin_sales_summary',
                      'title': '채널별 매출/마진',
                      'visualization': '상태 바'},
                     {'id': 'fin_budget',
                      'sql': '\n'
                             '                SELECT department_name, period, SUM(budget_krw) AS budget_krw\n'
                             '                FROM cos_adb.silver.fin_budget_plan\n'
                             '                GROUP BY department_name, period\n'
                             '                ORDER BY budget_krw DESC\n'
                             '                LIMIT 20\n'
                             '            ',
                      'table': 'cos_adb.silver.fin_budget_plan',
                      'title': '부서별 예산',
                      'visualization': '비교 바'},
                     {'id': 'fin_campaign_roi',
                      'sql': '\n'
                             '                SELECT channel,\n'
                             '                       SUM(attributed_sales_krw) AS attributed_sales_krw,\n'
                             '                       ROUND(AVG(roas), 4) AS avg_roas\n'
                             '                FROM cos_adb.silver.fin_campaign_sales_attribution\n'
                             '                GROUP BY channel\n'
                             '                ORDER BY attributed_sales_krw DESC\n'
                             '            ',
                      'table': 'cos_adb.silver.fin_campaign_sales_attribution',
                      'title': '캠페인 ROI',
                      'visualization': '산점도'},
                     {'id': 'fin_expenses',
                      'sql': '\n'
                             '                SELECT department_name, expense_category, SUM(amount_krw) AS amount_krw\n'
                             '                FROM cos_adb.silver.fin_expense_records\n'
                             '                GROUP BY department_name, expense_category\n'
                             '                ORDER BY amount_krw DESC\n'
                             '                LIMIT 20\n'
                             '            ',
                      'table': 'cos_adb.silver.fin_expense_records',
                      'title': '경비 현황',
                      'visualization': '바 차트'}],
 'HR_MANAGER': [{'id': 'hr_headcount_status',
                 'sql': '\n'
                        '                SELECT department_name,\n'
                        '                       employment_status,\n'
                        '                       COUNT(*) AS employee_count\n'
                        '                FROM cos_adb.silver.employees\n'
                        '                GROUP BY department_name, employment_status\n'
                        '                ORDER BY employee_count DESC\n'
                        '                LIMIT 20\n'
                        '            ',
                 'table': 'cos_adb.silver.employees',
                 'title': '부서별 재직 상태',
                 'visualization': '스택 바'},
                {'id': 'hr_clearance_distribution',
                 'sql': '\n'
                        '                SELECT security_clearance,\n'
                        '                       CAST(is_manager AS STRING) AS manager_flag,\n'
                        '                       COUNT(*) AS employee_count\n'
                        '                FROM cos_adb.silver.employees\n'
                        '                GROUP BY security_clearance, CAST(is_manager AS STRING)\n'
                        '                ORDER BY employee_count DESC\n'
                        '            ',
                 'table': 'cos_adb.silver.employees',
                 'title': '보안등급/관리자 분포',
                 'visualization': '히트맵'},
                {'id': 'hr_payroll_band',
                 'sql': '\n'
                        '                SELECT annual_salary_band_krw,\n'
                        '                       COUNT(*) AS employee_count,\n'
                        '                       ROUND(AVG(monthly_gross_pay_krw), 0) AS avg_monthly_gross_pay_krw\n'
                        '                FROM cos_adb.silver.hr_payroll_summary\n'
                        '                GROUP BY annual_salary_band_krw\n'
                        '                ORDER BY employee_count DESC\n'
                        '            ',
                 'table': 'cos_adb.silver.hr_payroll_summary',
                 'title': '급여 밴드 집계',
                 'visualization': '바 차트'}],
 'MARKETING_STAFF': [{'id': 'mkt_campaign_status',
                      'sql': '\n'
                             '                SELECT campaign_name, product_name, campaign_start_date, '
                             'budget_band_krw, ra_approval_status\n'
                             '                FROM cos_adb.silver.mkt_campaign_plan\n'
                             '                ORDER BY campaign_start_date DESC\n'
                             '                LIMIT 20\n'
                             '            ',
                      'table': 'cos_adb.silver.mkt_campaign_plan',
                      'title': '캠페인 계획 현황',
                      'visualization': '테이블'},
                     {'id': 'mkt_sns_platform',
                      'sql': '\n'
                             '                SELECT platform,\n'
                             '                       SUM(impressions) AS impressions,\n'
                             '                       SUM(clicks) AS clicks,\n'
                             '                       ROUND(AVG(engagement_rate), 4) AS avg_engagement_rate\n'
                             '                FROM cos_adb.silver.mkt_sns_performance\n'
                             '                GROUP BY platform\n'
                             '                ORDER BY impressions DESC\n'
                             '            ',
                      'table': 'cos_adb.silver.mkt_sns_performance',
                      'title': 'SNS 플랫폼 성과',
                      'visualization': '도넛'},
                     {'id': 'mkt_ad_review',
                      'sql': '\n'
                             '                SELECT restricted_claim_removed, COUNT(*) AS review_count\n'
                             '                FROM cos_adb.silver.mkt_ad_copy_review\n'
                             '                GROUP BY restricted_claim_removed\n'
                             '                ORDER BY review_count DESC\n'
                             '            ',
                      'table': 'cos_adb.silver.mkt_ad_copy_review',
                      'title': '광고 카피 심의 상태',
                      'visualization': '상태 테이블'},
                     {'id': 'mkt_product_info',
                      'sql': '\n'
                             '                SELECT product_name, product_line, launch_status, target_claim_summary\n'
                             '                FROM cos_adb.silver.rnd_product_master\n'
                             '                ORDER BY product_name\n'
                             '                LIMIT 20\n'
                             '            ',
                      'table': 'cos_adb.silver.rnd_product_master',
                      'title': '제품 기본 정보',
                      'visualization': '필터 테이블'}],
 'PRODUCTION_MANAGER': [{'id': 'prod_plan_status',
                         'sql': '\n'
                                '                SELECT plan_status,\n'
                                '                       COUNT(*) AS plan_count,\n'
                                '                       SUM(planned_quantity) AS planned_quantity\n'
                                '                FROM cos_adb.silver.mfg_production_plan\n'
                                '                GROUP BY plan_status\n'
                                '                ORDER BY plan_count DESC\n'
                                '            ',
                         'table': 'cos_adb.silver.mfg_production_plan',
                         'title': '생산 계획 상태',
                         'visualization': '상태 바'},
                        {'id': 'prod_work_orders',
                         'sql': '\n'
                                '                SELECT work_order_status, line_id, COUNT(*) AS work_order_count\n'
                                '                FROM cos_adb.silver.mfg_work_orders\n'
                                '                GROUP BY work_order_status, line_id\n'
                                '                ORDER BY work_order_count DESC\n'
                                '                LIMIT 20\n'
                                '            ',
                         'table': 'cos_adb.silver.mfg_work_orders',
                         'title': '작업지시 라인 현황',
                         'visualization': '도넛'},
                        {'id': 'prod_batch_records',
                         'sql': '\n'
                                '                SELECT record_status,\n'
                                '                       issue_flag,\n'
                                '                       COUNT(*) AS batch_count\n'
                                '                FROM cos_adb.silver.mfg_batch_manufacturing_records\n'
                                '                GROUP BY record_status, issue_flag\n'
                                '                ORDER BY batch_count DESC\n'
                                '            ',
                         'table': 'cos_adb.silver.mfg_batch_manufacturing_records',
                         'title': '배치 기록/이슈 현황',
                         'visualization': '상태 테이블'},
                        {'id': 'prod_schedule_calendar',
                         'sql': '\n'
                                '                SELECT product_name,\n'
                                '                       planned_start_date,\n'
                                '                       plan_status,\n'
                                '                       planned_quantity\n'
                                '                FROM cos_adb.silver.mfg_production_plan\n'
                                '                ORDER BY planned_start_date DESC\n'
                                '                LIMIT 12\n'
                                '            ',
                         'table': 'cos_adb.silver.mfg_production_plan',
                         'title': '생산 일정 캘린더',
                         'visualization': '캘린더'}],
 'QA_MANAGER': [{'id': 'qa_deviation_severity',
                 'sql': '\n'
                        '                SELECT severity, status, COUNT(*) AS deviation_count\n'
                        '                FROM cos_adb.silver.qa_deviation_reports\n'
                        '                GROUP BY severity, status\n'
                        '                ORDER BY deviation_count DESC\n'
                        '            ',
                 'table': 'cos_adb.silver.qa_deviation_reports',
                 'title': '일탈 건수 및 심각도',
                 'visualization': '히트맵'},
                {'id': 'qa_capa_status',
                 'sql': '\n'
                        '                SELECT status,\n'
                        '                       COUNT(*) AS capa_count,\n'
                        '                       SUM(CASE\n'
                        '                             WHEN to_date(due_date) < current_date()\n'
                        "                                  AND UPPER(status) NOT IN ('CLOSED', 'COMPLETED', 'DONE')\n"
                        '                             THEN 1 ELSE 0\n'
                        '                           END) AS overdue_count\n'
                        '                FROM cos_adb.silver.qa_capa_records\n'
                        '                GROUP BY status\n'
                        '                ORDER BY capa_count DESC\n'
                        '            ',
                 'table': 'cos_adb.silver.qa_capa_records',
                 'title': 'CAPA 진행/초과 현황',
                 'visualization': '상태 바'},
                {'id': 'qa_qc_result_status',
                 'sql': '\n'
                        '                SELECT result_status,\n'
                        '                       COUNT(*) AS result_count\n'
                        '                FROM cos_adb.silver.qa_qc_test_results\n'
                        '                GROUP BY result_status\n'
                        '                ORDER BY result_count DESC\n'
                        '            ',
                 'table': 'cos_adb.silver.qa_qc_test_results',
                 'title': 'QC 시험 판정',
                 'visualization': '상태 바'},
                {'id': 'qa_voc_quality_signal',
                 'sql': '\n'
                        '                SELECT product_name,\n'
                        '                       SUM(skin_reaction_mentions) AS skin_reaction_mentions,\n'
                        '                       ROUND(AVG(sentiment_score), 4) AS avg_sentiment_score,\n'
                        '                       MAX(claim_signal_level) AS claim_signal_level\n'
                        '                FROM cos_adb.silver.voc_review_voc_insights\n'
                        '                GROUP BY product_name\n'
                        '                ORDER BY skin_reaction_mentions DESC, avg_sentiment_score ASC\n'
                        '                LIMIT 12\n'
                        '            ',
                 'table': 'cos_adb.silver.voc_review_voc_insights',
                 'title': 'VOC 품질 신호',
                 'visualization': '경보 테이블'}],
 'RND_MANAGER': [{'id': 'rnd_portfolio',
                  'sql': '\n'
                         '                SELECT product_line, launch_status, business_model, COUNT(*) AS '
                         'product_count\n'
                         '                FROM cos_adb.silver.rnd_product_master\n'
                         '                GROUP BY product_line, launch_status, business_model\n'
                         '                ORDER BY product_count DESC\n'
                         '            ',
                  'table': 'cos_adb.silver.rnd_product_master',
                  'title': '제품 포트폴리오',
                  'visualization': '트리맵'},
                 {'id': 'rnd_improvement',
                  'sql': '\n'
                         '                SELECT action_status, source_type, COUNT(*) AS action_count\n'
                         '                FROM cos_adb.silver.rnd_product_improvement_actions\n'
                         '                GROUP BY action_status, source_type\n'
                         '                ORDER BY action_count DESC\n'
                         '            ',
                  'table': 'cos_adb.silver.rnd_product_improvement_actions',
                  'title': '제품 개선 조치',
                  'visualization': '상태 바'},
                 {'id': 'rnd_voc_product_signal',
                  'sql': '\n'
                         '                SELECT product_name,\n'
                         '                       SUM(review_count) AS review_count,\n'
                         '                       ROUND(AVG(average_rating), 3) AS average_rating,\n'
                         '                       SUM(skin_reaction_mentions) AS skin_reaction_mentions,\n'
                         '                       MAX(claim_signal_level) AS claim_signal_level\n'
                         '                FROM cos_adb.silver.voc_review_voc_insights\n'
                         '                GROUP BY product_name\n'
                         '                ORDER BY skin_reaction_mentions DESC, review_count DESC\n'
                         '                LIMIT 12\n'
                         '            ',
                  'table': 'cos_adb.silver.voc_review_voc_insights',
                  'title': '제품별 VOC 신호',
                  'visualization': '경보 테이블'},
                 {'id': 'rnd_material_watch',
                  'sql': '\n'
                         '                SELECT raw_material_name,\n'
                         '                       available_quantity_kg,\n'
                         '                       reorder_threshold_kg,\n'
                         '                       CASE\n'
                         "                         WHEN available_quantity_kg <= reorder_threshold_kg THEN 'REORDER'\n"
                         "                         ELSE 'OK'\n"
                         '                       END AS inventory_alert\n'
                         '                FROM cos_adb.silver.scm_raw_material_inventory\n'
                         '                ORDER BY inventory_alert DESC, available_quantity_kg ASC\n'
                         '                LIMIT 12\n'
                         '            ',
                  'table': 'cos_adb.silver.scm_raw_material_inventory',
                  'title': '원료 재고 리스크',
                  'visualization': '상태 테이블'}],
 'SCM_MANAGER': [{'id': 'scm_inventory_alert',
                  'sql': '\n'
                         '                SELECT raw_material_name,\n'
                         '                       available_quantity_kg,\n'
                         '                       reorder_threshold_kg,\n'
                         '                       CASE WHEN available_quantity_kg <= reorder_threshold_kg THEN '
                         "'REORDER' ELSE 'OK' END AS inventory_alert\n"
                         '                FROM cos_adb.silver.scm_raw_material_inventory\n'
                         '                ORDER BY inventory_alert DESC, available_quantity_kg ASC\n'
                         '                LIMIT 20\n'
                         '            ',
                  'table': 'cos_adb.silver.scm_raw_material_inventory',
                  'title': '원자재 재고 경보',
                  'visualization': '상태 테이블'},
                 {'id': 'scm_supplier_grade',
                  'sql': '\n'
                         '                SELECT audit_grade, COUNT(*) AS supplier_count\n'
                         '                FROM cos_adb.silver.scm_supplier_master\n'
                         '                GROUP BY audit_grade\n'
                         '                ORDER BY supplier_count DESC\n'
                         '            ',
                  'table': 'cos_adb.silver.scm_supplier_master',
                  'title': '공급업체 감사 등급',
                  'visualization': '도넛'},
                 {'id': 'scm_purchase_status',
                  'sql': '\n'
                         '                SELECT approval_status,\n'
                         '                       COUNT(*) AS po_count,\n'
                         '                       SUM(ordered_quantity_kg) AS ordered_quantity_kg\n'
                         '                FROM cos_adb.silver.scm_purchase_orders\n'
                         '                GROUP BY approval_status\n'
                         '                ORDER BY po_count DESC\n'
                         '            ',
                  'table': 'cos_adb.silver.scm_purchase_orders',
                  'title': '구매 주문 상태',
                  'visualization': '도넛'},
                 {'id': 'scm_delivery_status',
                  'sql': '\n'
                         '                SELECT delivery_status, receiving_site, COUNT(*) AS delivery_count\n'
                         '                FROM cos_adb.silver.scm_delivery_schedule\n'
                         '                GROUP BY delivery_status, receiving_site\n'
                         '                ORDER BY delivery_count DESC\n'
                         '            ',
                  'table': 'cos_adb.silver.scm_delivery_schedule',
                  'title': '배송 일정 준수',
                  'visualization': '상태 바'},
                 {'id': 'scm_finished_goods',
                  'sql': '\n'
                         '                SELECT product_name, warehouse_location, available_units, reserved_units, '
                         'inventory_status\n'
                         '                FROM cos_adb.silver.dist_finished_goods_inventory\n'
                         '                ORDER BY available_units DESC\n'
                         '                LIMIT 20\n'
                         '            ',
                  'table': 'cos_adb.silver.dist_finished_goods_inventory',
                  'title': '완제품 재고',
                  'visualization': '테이블'}]}

SqlExecutor = Callable[[str], tuple[list[str], list[dict[str, Any]]]]


def dashboard_roles_payload(role_access: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "role_id": role_id,
            "label": label,
            "role_name": role_access.get(role_id, {}).get("role_name", role_id),
            "department": role_access.get(role_id, {}).get("department", "-"),
        }
        for role_id, label in DATA_DASHBOARD_ROLE_LABELS.items()
    ]


def run_dashboard_metric(metric: dict[str, Any], execute_sql: SqlExecutor, configured: bool) -> dict[str, Any]:
    if not configured:
        result = {
            "status": "NOT_CONFIGURED",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "error": "DATABRICKS_SQL_WAREHOUSE_ID or DATABRICKS_WAREHOUSE_ID is not configured.",
        }
    else:
        try:
            columns, rows = execute_sql(metric["sql"])
            result = {
                "status": "SUCCESS",
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "error": None,
            }
        except Exception as exc:
            result = {
                "status": "QUERY_FAILED",
                "columns": [],
                "rows": [],
                "row_count": 0,
                "error": str(exc),
            }

    return {
        "id": metric["id"],
        "title": metric["title"],
        "table": metric["table"],
        "visualization": metric["visualization"],
        "status": result["status"],
        "columns": result["columns"],
        "rows": result["rows"],
        "row_count": result["row_count"],
        "error": result["error"],
    }


def build_data_dashboard(
    role_id: str,
    role_access: dict[str, dict[str, Any]],
    execute_sql: SqlExecutor,
    configured: bool,
) -> dict[str, Any]:
    normalized_role = role_id.upper()
    selected_role = normalized_role if normalized_role in DATA_DASHBOARD_ROLE_LABELS else "QA_MANAGER"
    access = role_access.get(selected_role, {})
    role_metrics = ROLE_DASHBOARD_METRICS.get(selected_role, [])
    common_metrics = [run_dashboard_metric(metric, execute_sql, configured) for metric in COMMON_DASHBOARD_METRICS]
    role_specific_metrics = [run_dashboard_metric(metric, execute_sql, configured) for metric in role_metrics]

    return {
        "role_id": selected_role,
        "label": DATA_DASHBOARD_ROLE_LABELS[selected_role],
        "role_name": access.get("role_name", selected_role),
        "department": access.get("department", "-"),
        "default_clearance": access.get("default_clearance", "-"),
        "systems": access.get("systems", []),
        "domains": access.get("domains", []),
        "allowed_tables": access.get("tables", []),
        "common_metrics": common_metrics,
        "role_metrics": role_specific_metrics,
        "all_metrics": common_metrics + role_specific_metrics,
        "databricks_sql_configured": configured,
    }
