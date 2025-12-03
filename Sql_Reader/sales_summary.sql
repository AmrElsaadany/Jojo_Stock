-- sales_summary.sql
-- Get sales summary with product details
SELECT 
    p.id,
    p.name,
    p.category,
    p.price,
    COUNT(s.id) as total_sales,
    SUM(s.quantity) as total_quantity_sold,
    ROUND(SUM(s.quantity) * p.price, 2) as total_revenue
FROM products p
LEFT JOIN sales s ON p.id = s.product_id
GROUP BY p.id, p.name, p.category, p.price
ORDER BY total_revenue DESC;
