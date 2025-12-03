-- get_all_products.sql
-- Retrieve all products from the database
SELECT 
    id,
    name,
    price,
    category,
    stock
FROM products
ORDER BY name;
