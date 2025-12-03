-- high_value_products.sql
-- Find products with price above average
SELECT 
    name,
    category,
    price,
    stock,
    ROUND(price, 2) as formatted_price
FROM products
WHERE price > (SELECT AVG(price) FROM products)
ORDER BY price DESC;
