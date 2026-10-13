package org.hibernate.annotations; public @interface OnDelete { OnDeleteAction action() default OnDeleteAction.NO_ACTION; }
