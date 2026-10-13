package jakarta.persistence;
public @interface Column { String name() default ""; boolean unique() default false; boolean nullable() default true; boolean insertable() default true; boolean updatable() default true; String columnDefinition() default ""; int length() default 255; int precision() default 0; int scale() default 0; }
