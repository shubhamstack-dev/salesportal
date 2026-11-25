/// <summary>
/// Posting for the Samurai Sales Portal. Assigns lot numbers to sales order lines first-expiry-first-out (FEFO)
/// and posts the order (Ship and Invoice) for the Qty. to Ship / Qty. to Invoice the portal has set on its lines.
/// </summary>
codeunit 50120 "SF Portal Posting"
{
    Permissions = tabledata "Reservation Entry" = rimd;

    var
        NotEnoughLotsErr: Label 'Not enough stock with lot numbers for item %1 at location %2: %3 short. Post a positive adjustment or transfer, or assign the lots on the order by hand.', Comment = '%1 = item no., %2 = location, %3 = quantity short';

    /// <summary>Assigns missing lot numbers, then posts the order (Ship and Invoice).</summary>
    procedure AssignLotsAndPost(var SalesHeader: Record "Sales Header")
    begin
        SalesHeader.TestField("Document Type", SalesHeader."Document Type"::Order);
        AssignLots(SalesHeader);
        SalesHeader.Ship := true;
        SalesHeader.Invoice := true;
        Codeunit.Run(Codeunit::"Sales-Post", SalesHeader);
    end;

    /// <summary>
    /// For each item line with a Qty. to Ship whose item needs lot numbers when sold, and that has no item tracking
    /// yet, assigns lots from the open stock at the line's location: earliest expiry first, lots without an expiry
    /// date last. Lines that already have tracking (assigned by hand) are left as they are.
    /// </summary>
    procedure AssignLots(var SalesHeader: Record "Sales Header")
    var
        SalesLine: Record "Sales Line";
    begin
        SalesLine.SetRange("Document Type", SalesHeader."Document Type");
        SalesLine.SetRange("Document No.", SalesHeader."No.");
        SalesLine.SetRange(Type, SalesLine.Type::Item);
        SalesLine.SetFilter("Qty. to Ship (Base)", '>0');
        if SalesLine.FindSet() then
            repeat
                if NeedsLot(SalesLine."No.") then
                    if not HasTracking(SalesLine) then
                        AssignLotsToLine(SalesLine);
            until SalesLine.Next() = 0;
    end;

    local procedure NeedsLot(ItemNo: Code[20]): Boolean
    var
        Item: Record Item;
        ItemTrackingCode: Record "Item Tracking Code";
    begin
        if not Item.Get(ItemNo) then
            exit(false);
        if Item."Item Tracking Code" = '' then
            exit(false);
        if not ItemTrackingCode.Get(Item."Item Tracking Code") then
            exit(false);
        exit(ItemTrackingCode."Lot Specific Tracking" or ItemTrackingCode."Lot Sales Outbound Tracking");
    end;

    local procedure HasTracking(SalesLine: Record "Sales Line"): Boolean
    var
        ReservEntry: Record "Reservation Entry";
    begin
        ReservEntry.SetRange("Source Type", Database::"Sales Line");
        ReservEntry.SetRange("Source Subtype", SalesLine."Document Type".AsInteger());
        ReservEntry.SetRange("Source ID", SalesLine."Document No.");
        ReservEntry.SetRange("Source Ref. No.", SalesLine."Line No.");
        ReservEntry.SetFilter("Lot No.", '<>%1', '');
        exit(not ReservEntry.IsEmpty());
    end;

    local procedure AssignLotsToLine(SalesLine: Record "Sales Line")
    var
        ItemLedgEntry: Record "Item Ledger Entry";
        Lots: List of [Code[50]];
        Expiry: Dictionary of [Code[50], Date];
        Remaining: Dictionary of [Code[50], Decimal];
        Lot: Code[50];
        Need: Decimal;
        Avail: Decimal;
        Take: Decimal;
    begin
        Need := SalesLine."Qty. to Ship (Base)";
        ItemLedgEntry.SetRange("Item No.", SalesLine."No.");
        ItemLedgEntry.SetRange("Variant Code", SalesLine."Variant Code");
        ItemLedgEntry.SetRange("Location Code", SalesLine."Location Code");
        ItemLedgEntry.SetRange(Open, true);
        ItemLedgEntry.SetRange(Positive, true);
        ItemLedgEntry.SetFilter("Lot No.", '<>%1', '');
        if ItemLedgEntry.FindSet() then
            repeat
                if Remaining.ContainsKey(ItemLedgEntry."Lot No.") then
                    Remaining.Set(ItemLedgEntry."Lot No.", Remaining.Get(ItemLedgEntry."Lot No.") + ItemLedgEntry."Remaining Quantity")
                else begin
                    Remaining.Add(ItemLedgEntry."Lot No.", ItemLedgEntry."Remaining Quantity");
                    Expiry.Add(ItemLedgEntry."Lot No.", ItemLedgEntry."Expiration Date");
                    InsertByExpiry(Lots, Expiry, ItemLedgEntry."Lot No.");
                end;
            until ItemLedgEntry.Next() = 0;

        foreach Lot in Lots do
            if Need > 0 then begin
                Avail := Remaining.Get(Lot) - Committed(SalesLine, Lot);
                if Avail > 0 then begin
                    Take := Avail;
                    if Take > Need then
                        Take := Need;
                    CreateLotTracking(SalesLine, Lot, Expiry.Get(Lot), Take);
                    Need -= Take;
                end;
            end;

        if Need > 0 then
            Error(NotEnoughLotsErr, SalesLine."No.", SalesLine."Location Code", Need);
    end;

    local procedure InsertByExpiry(var Lots: List of [Code[50]]; Expiry: Dictionary of [Code[50], Date]; Lot: Code[50])
    var
        i: Integer;
    begin
        for i := 1 to Lots.Count() do
            if SortDate(Expiry.Get(Lot)) < SortDate(Expiry.Get(Lots.Get(i))) then begin
                Lots.Insert(i, Lot);
                exit;
            end;
        Lots.Add(Lot);
    end;

    local procedure SortDate(D: Date): Date
    begin
        if D = 0D then
            exit(DMY2Date(31, 12, 9999));
        exit(D);
    end;

    /// <summary>What other documents have already claimed of a lot at the location (outbound tracking and reservations).</summary>
    local procedure Committed(SalesLine: Record "Sales Line"; Lot: Code[50]): Decimal
    var
        ReservEntry: Record "Reservation Entry";
    begin
        ReservEntry.SetRange("Item No.", SalesLine."No.");
        ReservEntry.SetRange("Variant Code", SalesLine."Variant Code");
        ReservEntry.SetRange("Location Code", SalesLine."Location Code");
        ReservEntry.SetRange("Lot No.", Lot);
        ReservEntry.SetRange(Positive, false);
        ReservEntry.CalcSums("Quantity (Base)");
        exit(-ReservEntry."Quantity (Base)");
    end;

    /// <summary>Item tracking line on the sales line for one lot (what the Item Tracking Lines page creates).</summary>
    local procedure CreateLotTracking(SalesLine: Record "Sales Line"; Lot: Code[50]; ExpirationDate: Date; QtyBase: Decimal)
    var
        TempReservEntry: Record "Reservation Entry" temporary;
        CreateReservEntry: Codeunit "Create Reserv. Entry";
        Qty: Decimal;
    begin
        Qty := Round(QtyBase / SalesLine."Qty. per Unit of Measure", 0.00001);
        TempReservEntry."Lot No." := Lot;
        CreateReservEntry.SetDates(0D, ExpirationDate);
        // positive quantities: Create Reserv. Entry applies the sign of the source (negative for a sales order)
        CreateReservEntry.CreateReservEntryFor(
            Database::"Sales Line", SalesLine."Document Type".AsInteger(), SalesLine."Document No.", '', 0, SalesLine."Line No.",
            SalesLine."Qty. per Unit of Measure", Qty, QtyBase, TempReservEntry);
        CreateReservEntry.CreateEntry(
            SalesLine."No.", SalesLine."Variant Code", SalesLine."Location Code", SalesLine.Description,
            0D, SalesLine."Shipment Date", 0, "Reservation Status"::Surplus);
    end;
}
