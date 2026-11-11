{
    "name": "Social LinkedIn extended",
    "summary": "LinkedIn comment diagnostics for Social Marketing",
    "version": "19.0.1.0.0",
    "category": "Marketing/Social Marketing",
    "license": "AGPL-3",
    "author": "Zinapsia",
    "website": "https://www.zinapsia.com",
    "depends": [
        "social",
        "social_linkedin",
        "utm",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_config_parameter_data.xml",
        "wizard/social_linkedin_comment_test_views.xml",
        "views/social_account_views.xml",
    ],
    "auto_install": False,
    "application": False,
    "installable": True,
}
