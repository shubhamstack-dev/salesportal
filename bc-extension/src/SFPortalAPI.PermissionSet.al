permissionset 50120 "SF PORTAL API"
{
    Assignable = true;
    Caption = 'Samurai Sales Portal API';
    Permissions =
        codeunit "SF Portal Posting" = X,
        page "SF Portal Sales Orders" = X,
        tabledata "Reservation Entry" = RIMD;
}
