/// <summary>
/// API for the Samurai Sales Portal:
///   POST .../api/samuraiFoods/portal/v1.0/companies({id})/portalSalesOrders({orderId})/Microsoft.NAV.assignLotsAndPost
///   POST .../api/samuraiFoods/portal/v1.0/companies({id})/portalSalesOrders({orderId})/Microsoft.NAV.assignLots
/// {orderId} is the same id as in the standard API (salesOrders), the order's SystemId.
/// </summary>
page 50120 "SF Portal Sales Orders"
{
    PageType = API;
    APIPublisher = 'samuraiFoods';
    APIGroup = 'portal';
    APIVersion = 'v1.0';
    EntityName = 'portalSalesOrder';
    EntitySetName = 'portalSalesOrders';
    EntityCaption = 'Portal Sales Order';
    EntitySetCaption = 'Portal Sales Orders';
    SourceTable = "Sales Header";
    SourceTableView = where("Document Type" = const(Order));
    ODataKeyFields = SystemId;
    DelayedInsert = true;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(Records)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'Id';
                    Editable = false;
                }
                field(number; Rec."No.")
                {
                    Caption = 'No.';
                    Editable = false;
                }
                field(customerNumber; Rec."Sell-to Customer No.")
                {
                    Caption = 'Customer No.';
                    Editable = false;
                }
                field(postingDate; Rec."Posting Date")
                {
                    Caption = 'Posting Date';
                    Editable = false;
                }
                field(lastPostingNumber; Rec."Last Posting No.")
                {
                    Caption = 'Last Posting No.';
                    Editable = false;
                }
            }
        }
    }

    [ServiceEnabled]
    procedure assignLotsAndPost(var ActionContext: WebServiceActionContext)
    var
        PortalPosting: Codeunit "SF Portal Posting";
    begin
        PortalPosting.AssignLotsAndPost(Rec);
        ActionContext.SetResultCode(WebServiceActionResultCode::Updated);
    end;

    [ServiceEnabled]
    procedure assignLots(var ActionContext: WebServiceActionContext)
    var
        PortalPosting: Codeunit "SF Portal Posting";
    begin
        PortalPosting.AssignLots(Rec);
        ActionContext.SetResultCode(WebServiceActionResultCode::Updated);
    end;
}
