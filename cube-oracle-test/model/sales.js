cube('SalesSummary', {
  sql: `SELECT * FROM testuser.v_sales_summary`,

  measures: {
    totalAmount: {
      sql: `total_amount`,
      type: `sum`,
      title: '총 매출액'
    },
    totalQuantity: {
      sql: `quantity`,
      type: `sum`,
      title: '총 수량'
    },
    avgDealSize: {
      sql: `total_amount`,
      type: `avg`,
      title: '평균 거래 금액'
    },
    dealCount: {
      type: `count`,
      title: '거래 건수'
    },
    largeDealCount: {
      sql: `CASE WHEN is_large_deal = 'Y' THEN 1 END`,
      type: `count`,
      title: '대형 거래 건수'
    }
  },

  dimensions: {
    saleDate: {
      sql: `sale_date`,
      type: `time`,
      title: '거래일'
    },
    deptName: {
      sql: `dept_name`,
      type: `string`,
      title: '부서명'
    },
    productName: {
      sql: `product_name`,
      type: `string`,
      title: '제품명'
    },
    category: {
      sql: `category`,
      type: `string`,
      title: '카테고리'
    },
    customerName: {
      sql: `customer_name`,
      type: `string`,
      title: '고객사'
    },
    region: {
      sql: `region`,
      type: `string`,
      title: '지역'
    },
    isLargeDeal: {
      sql: `is_large_deal`,
      type: `string`,
      title: '대형 거래 여부 (Y/N)'
    },
    isSoftware: {
      sql: `is_software`,
      type: `string`,
      title: '소프트웨어 여부 (Y/N)'
    }
  }
});

cube('DeptPerformance', {
  sql: `SELECT * FROM testuser.v_dept_monthly_performance`,

  measures: {
    totalRevenue: {
      sql: `revenue`,
      type: `sum`,
      title: '총 매출'
    },
    totalCost: {
      sql: `cost`,
      type: `sum`,
      title: '총 비용'
    },
    totalProfit: {
      sql: `profit`,
      type: `sum`,
      title: '총 이익'
    },
    avgSatisfaction: {
      sql: `satisfaction_score`,
      type: `avg`,
      title: '평균 만족도'
    },
    totalHeadcount: {
      sql: `headcount`,
      type: `sum`,
      title: '총 인원'
    },
    totalCustomers: {
      sql: `customer_count`,
      type: `sum`,
      title: '총 고객수'
    }
  },

  dimensions: {
    kpiMonth: {
      sql: `kpi_month`,
      type: `time`,
      title: 'KPI 월'
    },
    deptName: {
      sql: `dept_name`,
      type: `string`,
      title: '부서명'
    },
    isProfitable: {
      sql: `is_profitable`,
      type: `string`,
      title: '흑자 여부 (Y/N)'
    },
    isHighSatisfaction: {
      sql: `is_high_satisfaction`,
      type: `string`,
      title: '고만족 여부 (Y/N)'
    },
    profitMarginPct: {
      sql: `profit_margin_pct`,
      type: `number`,
      title: '이익률 (%)'
    }
  }
});
